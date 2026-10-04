# Local ICONA protocol (port 64100)

Notes on the conversation between client and monitor on the local network. Tested on 6741W (internal model `MSVF`, firmware 2.1.0). The addresses in the examples are fictitious. Italian version: [docs/PROTOCOL.md](../PROTOCOL.md).

Where a point comes from public references for the 6701W and was not re-tested on the 6741W, it is marked as such.

## Frame

Every message, over TCP, has an 8-byte header:

```
00 06        constant
LL LL        body length, uint16 little-endian
CC CC        channel id, uint16 little-endian (0 = channel management)
00 00        padding
...          body
```

The body is JSON (starts with `{`, UTF-8, no spaces) or binary.

## Opening a channel

The client asks for a channel by name on channel 0:

```
cd ab            COMMAND (0xABCD)
01 00            sequence, must be 1
07 00 00 00      type
55 41 55 54      name, 4 ASCII letters (here "UAUT")
94 57            client-chosen id
00
[00 + length LE32 + string + 00]   extra data, only for some channels
```

The monitor answers, also on channel 0:

```
cd ab 02 00 04 00 00 00  <id LE16>  00 00
```

From then on the channel's frames carry that id in the header.

For the "type" field there are two conventions: name length plus 3 (so 7 for every four-letter name) or a per-channel value (UAUT 7, UCFG 2, INFO 20, CTPP 16, CSPB 17). On the 6741W both worked.

Close: `ef 01 03 00 02 00 00 00 <id LE16>`.

### Channels opened by the monitor

The monitor can also open a channel toward the client, with the same sequence-1 message. The client must acknowledge with the sequence-2 answer echoing the received id. On the local network, during a simple opening, this does not happen. On the remote path it always happens at the start (`ECHO` channel) and answering is mandatory: see [REMOTE_P2P.md](REMOTE_P2P.md).

## Channels

| Name | Content | Use |
|---|---|---|
| UAUT | JSON | authentication with the user-token |
| UCFG | JSON | configuration and address book |
| INFO | JSON | model, version, capabilities |
| PUSH | JSON | notification registration |
| CTPP | binary | call events, door opening |
| CSPB | binary | accompanies CTPP for continuous listening |
| ECHO | binary | keeping the remote session alive |

## Minimal session

```
UAUT  -> {"message":"access","user-token":"<32 hex>","message-type":"request","message-id":2}
      <- "response-code":200
UCFG  -> {"message":"get-configuration","addressbooks":"all","message-type":"request","message-id":3}
      <- "response-code":200 and a "vip" object
INFO  -> {"message":"server-info","message-type":"request","message-id":20}
```

In the UCFG response:

- `vip.apt-address` and `vip.apt-subaddress`: the address of your own unit, for example `SB000042` and `1`;
- `vip.user-parameters.opendoor-address-book`: entries `{id, name, apt-address, output-index}`;
- `vip.user-parameters.actuator-address-book`: as above, plus `module-index`.

The client refuses the session if the monitor declares `encryption-required`.

## CTPP messages

General shape:

```
[prefix LE16][counter LE32][action BE16][parameter BE16] ... ff ff ff ff [caller\0][callee\0]
```

Note: prefix and counter are little-endian, action and parameter big-endian. Addresses are ASCII terminated by zero after the `ff ff ff ff` separator.

| Prefix | Meaning |
|---|---|
| 0x18C0 | start (registration or call) |
| 0x1800 | acknowledgement |
| 0x1820 | acknowledgement of the acknowledgement |
| 0x1840 | call signalling |
| 0x1860 | state events |

Actions on 0x1860: `0x0001` ring, `0x0003` door opened, `0x0010` registration renewal. Only `0x0003` was verified on the 6741W; the others come from public references.

## Opening the gate

With no CTPP channel already open:

1. open CTPP with extra data equal to address plus sub-address (for example `SB0000421`);
2. send the registration (prefix 0x18C0);
3. send the sequence: request (0x1800), confirm (0x1820), open init (0x18C0 with the entrance panel address and relay), request, confirm;
4. read for a couple of seconds: the monitor emits `0x1860 / 0x0003` with the entrance panel address.

The event at step 4 is what the client reports as `opened_confirmed`. It must not be acknowledged in turn. It means the device executed, not that the lock moved.

For an actuator the sequence is shorter (init, request, confirm) and was derived only for module 255 and relay 1: the client refuses other values rather than trying.

Possible outcomes: `opened_confirmed`, `sent_unconfirmed` (sent, no return event), `delivery_uncertain` (error while sending: the command is not repeated).

## Other ports of the monitor

| Port | Use |
|---|---|
| 64100 TCP/UDP | ICONA |
| 24199 UDP | discovery: sending `INFO`, the monitor replies with its own data |
| 8080 / 8443 | web administration page |

## Not covered

Continuous event listening with registration renewal, video and audio call (RTP, H.264, G.711 A-law). The public references for the 6701W describe them; they are neither implemented nor verified here.
