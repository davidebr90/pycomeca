// Passive ARM64 observer. No credentials or application payloads emitted.
const module = Process.getModuleByName('libvipcomelit.so');
const exports = module.enumerateExports();
const counts = {};
function emit(value) { console.log(JSON.stringify({at_ms: Date.now(), ...value})); }
function hook(fragment, event, sizeArg) {
    const symbol = exports.find(e => e.name.includes(fragment));
    if (!symbol) { emit({event: 'missing_symbol', name: fragment}); return; }
    emit({event: 'attaching', name: fragment});
    Interceptor.attach(symbol.address, {
        onEnter(args) {
            counts[event] = (counts[event] || 0) + 1;
            const record = {event, count: counts[event]};
            if (sizeArg !== undefined) record.bytes = args[sizeArg].toInt32();
            emit(record);
        }
    });
    emit({event: 'attached', name: fragment});
}
hook('IceSession9startHttp', 'http_start');
hook('IceSession9startMqtt', 'mqtt_start');
hook('IceClient16processDataRxPck', 'ice_rx', 2);
hook('PseudoTcpSck6notify', 'pseudotcp_rx', 2);
hook('PseudoTcpSck8sendData', 'pseudotcp_tx', 2);
hook('ViperTunnel13handleP2PData', 'tunnel_rx');
hook('ViperTunnel9injectTCP', 'vip_tcp_rx', 2);
hook('ViperTunnel9injectUDP', 'vip_udp_rx', 2);
hook('ViperTunnel16sendOnCTPChannel', 'ctpp_tx', 2);
emit({event: 'ready', arch: Process.arch});
setInterval(() => emit({event: 'summary', counts}), 15000);
