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

## Full channel list

Beyond those used in the minimal session, the app also opens or meets these. Where not re-tested on the 6741W it is marked [R] (6701W reference).

| Name | Enum id | "type" field | Use |
|---|---|---|---|
| INFO | 0 | 20 | server information |
| PUSH | 1 | 2 | notifications |
| ECHO | 2 | 7 | keeping the remote session alive |
| UAUT | 3 | 7 | authentication |
| UADM | 4 | - | user administration [R] |
| UCFG | 5 | 2 | configuration |
| FACT | 6 | - | factory settings [R] |
| CTPP | 7 | 16 | events and opening |
| CSPB | 8 | 17 | accompanies CTPP |
| ECHO_SRV | 9 | - | server-side echo [R] |
| FRCG | 10 | 7 | face recognition |
| UDPM | - | - | media control during a call [R] |
| RTPC, RTPC2 | - | - | RTP flow during a call [R] |

The "type" field is the one observed in clear text (for four-letter names it is often 7). Media channels are opened with a final byte set to 1.

## CTPP: the three timestamp regimes

The CTPP channel uses three different ways of computing the timestamp in acknowledgements. Mixing them makes the device stop sending events, silently.

1. **Event acknowledgement** (for every `0x18C0`, `0x1840`, `0x1860` that is not a renewal): derived from the device's timestamp, setting the high bit of the first byte and swapping two bytes with an increment. [R]
2. **Renewal acknowledgement** (`0x1860 / 0x0010`): derived from your own init timestamp plus a fixed constant (`0x01010000`); answer with the pair `0x1800` then `0x1820`. Never derive it from the device's timestamp. A mistake here silently kills all events. [R]
3. **Call counters** (video setup): per-byte increments of the 32-bit field; the call's initial timestamp must differ from the init one in bytes 2-3, or the call is refused. [R]

Golden rule: the door-opened event `0x1860 / 0x0003` must never be acknowledged; any acknowledgement is refused and the device retransmits it a few times before stopping. That is why about three of them are seen. [D]

## Continuous event listening

To receive ring and opening continuously, instead of opening a transient CTPP for each opening you keep one CTPP (plus CSPB) open and handle registration renewal. [R]

1. open CTPP and CSPB;
2. send the initial registration (`0x18C0` with capability `0x18C2` on the 6741W [D], `0xAC23` in other references);
3. the device replies `0x1800` and enters the renewal cycle;
4. at each `0x1860 / 0x0010` answer with the pair of acknowledgements using timestamp regime 2;
5. rings arrive as `0x18C0` or `0x1860 / 0x0001`; opening as `0x1860 / 0x0003`.

For an always-on in-home listener, a dedicated sub-address is advisable, so the phone sharing the same token is not evicted. [R]

## Not covered in PyCOMECA

Continuous event listening and the video/audio call (UDPM/RTPC channels, RTP, H.264, G.711 A-law) are documented here but not implemented. The detail is in [CALL](CALL.md). The public references for the 6701W describe them; on the 6741W they largely remain to be re-tested.
