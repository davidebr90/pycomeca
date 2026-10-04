# How it was figured out

This is the study path, in order, with the tools used and the mistakes made. It may help anyone wanting to repeat the work on another model. Italian version: [docs/DEBUG_FLOW.md](../DEBUG_FLOW.md).

## Tools

- Android emulator with root access and the official app installed.
- [jadx](https://github.com/skylot/jadx) to read the app's code.
- [mitmproxy](https://mitmproxy.org/) with its certificate added to the system store, for the HTTPS traffic to the cloud.
- [Frida](https://frida.re/) to observe the app's calls while running (scripts in `tools/frida/`).
- `tcpdump` inside the emulator and Wireshark for UDP traffic.
- Temporary `iptables` rules inside the emulator to take the local network out of the picture.

## 1. Static reading of the app

The decompiled code gave up the cloud address, the OAuth login flow with PKCE, the channel names (`UAUT`, `UCFG`, `INFO`, `CTPP`, ...) and the three connection strategies the app tries in order: direct on the LAN, direct on a public IP, P2P via the cloud.

First mistake: I had concluded the opening was a REST call to the cloud. On my system the list of "smart" devices returned by the cloud is empty, so that path does not exist.

## 2. HTTPS traffic

With the proxy I saw the real login (endpoint, scope, response format) and the `p2p/start` call, which carries an SDP offer and receives the intercom's. The open command, however, does not go over HTTP.

## 3. Observing with Frida

Hooking the class the app uses to talk to the intercom, I saw the JSON messages on the channels in clear text and the open call with the entrance panel address and relay.

Second mistake: I had taken the `access` message on the `UAUT` channel for the open command. It is only authentication. Opening is a binary sequence on the `CTPP` channel.

Practical note: in the emulator the video decoder crashes the app. The `hook_bypass.js` script steps over it, and everything else (events, audio, opening) stays observable.

## 4. Local protocol

The frame format on port 64100 and the binary open sequence were already described by public projects for a nearby model. I rewrote them independently and tested them on my monitor: authentication, reading the configuration, opening, with the intercom sending back the door-opened event.

From here on, opening at home worked. The outside path remained.

## 5. Isolating the remote path

Third mistake: an open attempt from the emulator had succeeded and I had taken it as confirmation of the cloud path. Looking at the emulator's connection table there was instead a direct TCP link to the intercom: the emulator reaches the home LAN.

To really see the remote path I blocked, inside the emulator, all traffic to the intercom's local IP, restarted the app and captured the UDP. The result:

- a STUN exchange with a public server and nomination of an ICE pair;
- datagrams with a fixed 24-byte header, compatible with libnice's PseudoTCP;
- with the header removed and the segments reordered, the content is the same stream of protocol frames as the local path, **not encrypted**.

So the remote path is not a different protocol: it is the same conversation, carried over ICE and PseudoTCP.

## 6. Rebuilding the transport

From the captures I extracted the exact text of the two SDPs and the layout of the PseudoTCP header fields. I then wrote SDP, STUN, ICE and PseudoTCP in Python and verified them without an intercom: comparison against the captured bytes, reliable exchange with 30% packet loss, two real ICE agents over UDP, and finally the real client opening a door against a simulated device.

## 7. First live test and two surprises

On the first test the transport established at once, but the intercom did not answer. Two rules that do not exist on the LAN:

1. On the remote path the intercom speaks first: it opens an `ECHO` channel toward the client.
2. Until that open is acknowledged, everything the client sends is ignored.

I found the right order by re-reading the app's capture: first the `ECHO` channel acknowledgement, then opening `UAUT`. Once this was fixed, reading the configuration succeeded, even forcing the traffic through the public relay.

## Useful lessons

- Always check **which** network path a successful test actually used.
- An "ok" return value from an app function does not prove the connection is working.
- Keep live tests read-only until you need to open, and open only with someone at the gate.
- Write down the disproved hypotheses: half the time went into chasing the first two.
