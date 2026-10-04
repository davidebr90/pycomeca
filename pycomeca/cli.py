"""Local diagnostics and explicit Comelit controls."""
from __future__ import annotations
import argparse, ipaddress, json, logging, socket, sqlite3, sys, time
from pathlib import Path
from .client import IconaClient, AuthenticationError
from .profile import DeviceConfig, Profile, ROOT, redact
from .protocol import ProtocolError, door_sequence
from .research import discover, inspect_mitm, inspect_pcap, inspect_wire

def build_parser():
    p=argparse.ArgumentParser(description="Comelit VIP: diagnostica locale e controllo sperimentale")
    g=p.add_mutually_exclusive_group()
    g.add_argument("--list",action="store_true",help="legge UCFG (default)"); g.add_argument("--inventory",action="store_true")
    g.add_argument("--probe",action="store_true"); g.add_argument("--discover",action="store_true"); g.add_argument("--info",action="store_true")
    g.add_argument("--open",metavar="TARGET"); g.add_argument("--decode-hex",metavar="HEX"); g.add_argument("--analyze-captures",action="store_true")
    p.add_argument("--profile",type=Path,default=ROOT/"installation.local.json"); p.add_argument("--host"); p.add_argument("--port",type=int); p.add_argument("--timeout",type=float); p.add_argument("--wire-profile",choices=("classic","community")); p.add_argument("--system-id",type=int)
    p.add_argument("--from-config",type=Path); p.add_argument("--dry-run",action="store_true"); p.add_argument("--output",type=Path); p.add_argument("--captures-dir",type=Path,default=ROOT/"captures"); p.add_argument("--debug",action="store_true")
    return p

def emit(value, path=None):
    text=json.dumps(redact(value),ensure_ascii=False,indent=2)
    if path:
        if path.exists() or not path.parent.is_dir(): raise ValueError("--output deve essere un nuovo file in directory esistente")
        with path.open("x",encoding="utf-8") as f: f.write(text+"\n")
    print(text)

def analyze(directory):
    results=[]; candidates=[]; errors=[]
    paths=sorted(directory.glob("*.mitm"))+sorted(directory.glob("*.pcap"))
    if not paths: raise ValueError("Nessuna cattura .mitm o .pcap trovata")
    for path in paths:
        try:
            if path.suffix==".mitm":
                result, configs=inspect_mitm(path)
                for raw in configs:
                    try:
                        cfg=DeviceConfig.parse(raw); candidates.append({"file":path.name,"configuration":cfg.public(),"local_server":redact(raw.get("viper-server",{}))})
                    except ProtocolError: pass
            else: result=inspect_pcap(path)
            results.append(result)
        except (OSError,ValueError,TypeError) as e: errors.append({"file":path.name,"error_type":type(e).__name__})
    return {"status":"partial" if errors else "analyzed","captures":results,"configuration_candidates":candidates,"errors":errors}

def main(argv=None):
    a=build_parser().parse_args(argv)
    if a.dry_run and (not a.open or not a.from_config): raise SystemExit("--dry-run richiede --open e --from-config")
    if a.from_config and a.open and not a.dry_run:
        raise SystemExit("--from-config con --open richiede --dry-run; nessun comando inviato")
    if a.from_config and any((a.inventory, a.probe, a.discover, a.info, a.decode_hex is not None, a.analyze_captures)):
        raise SystemExit("--from-config supporta solo --list o --open con --dry-run")
    if a.output and (a.output.exists() or not a.output.parent.is_dir()): raise SystemExit("--output deve essere un nuovo file in directory esistente")
    logging.basicConfig(level=logging.DEBUG if a.debug else logging.WARNING,format="%(levelname)s %(message)s")
    client=None
    try:
        if a.decode_hex is not None: emit({"frames":inspect_wire(bytes.fromhex(a.decode_hex))},a.output); return 0
        if a.analyze_captures: result=analyze(a.captures_dir); emit(result,a.output); return 0 if not result["errors"] else 2
        if a.from_config:
            cfg=DeviceConfig.parse(json.loads(a.from_config.read_text(encoding="utf-8")))
            if a.open:
                target=cfg.select(a.open); payloads=door_sequence(cfg.apartment,target.address,target.relay,target.kind,target.module)
                if target.secure: raise ProtocolError("secure-mode non implementato")
                emit({"status":"dry_run","network_used":False,"target":target.public(),"experimental_on_msvf":True,"control_payloads_hex":[x.hex() for x in payloads]},a.output)
            else: emit({"source":"offline_configuration",**cfg.public()},a.output)
            return 0
        profile=Profile.load(a.profile,host=a.host,port=a.port,timeout=a.timeout,wire_profile=a.wire_profile,system_id=a.system_id)
        if a.inventory: emit(profile.inventory(),a.output); return 0
        if a.discover:
            r=discover(profile.host,min(profile.timeout,5)); emit(r,a.output); return 0 if r["status"]=="response_received" else 3
        if a.probe:
            started=time.monotonic(); family=socket.AF_INET6 if ipaddress.ip_address(profile.host).version==6 else socket.AF_INET
            with socket.socket(family,socket.SOCK_STREAM) as sock:
                sock.settimeout(profile.timeout)
                try: sock.connect((profile.host,profile.port)); r={"status":"tcp_connected","authentication":"not_attempted"}
                except OSError as e: r={"status":"unreachable","error_type":type(e).__name__,"errno":e.errno}
            r.update(host=profile.host,port=profile.port,elapsed_seconds=round(time.monotonic()-started,3)); emit(r,a.output); return 0 if r["status"]=="tcp_connected" else 3
        token=profile.token()
        with IconaClient(profile) as client:
            client.authenticate(token)
            if a.info: result={"status":"server_info_received","info":client.info()}
            else:
                cfg=client.configuration()
                result=client.open_target(cfg,cfg.select(a.open)) if a.open else {"status":"configuration_received","source":"device_live",**cfg.public()}
            result["transport"]={"frames_sent":client.frames_sent,"frames_received":client.frames_received}
        emit(result,a.output); return 4 if result.get("status")=="delivery_uncertain" else 0
    except AuthenticationError: emit({"status":"authentication_rejected","retry_performed":False}); return 2
    except (OSError,sqlite3.Error,ProtocolError,ValueError,TypeError,KeyError) as e:
        attempted=bool(client and client.control_attempted); r={"status":"delivery_uncertain" if attempted else "failed","error_type":type(e).__name__,"control_attempted":attempted,"retry_performed":False}
        if isinstance(e,ProtocolError): r["detail"]=str(e)
        emit(r); return 4 if attempted else 2
    except KeyboardInterrupt: emit({"status":"interrupted","control_attempted":bool(client and client.control_attempted),"physical_state":"unknown","retry_performed":False}); return 130

if __name__ == "__main__":
    raise SystemExit(main())
