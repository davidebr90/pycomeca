# Video call: signalling, video and audio

How a full call with the entrance panel works (video and two-way audio) and how the media flows. Italian version: [docs/CHIAMATA.md](../CHIAMATA.md).

This part is **not implemented** in PyCOMECA and **was not re-tested on the 6741W**: it is documented for completeness, mostly from public references verified on captures for the 6701W. Evidence level:

- **[R]** 6701W reference, not re-tested here;
- **[D]** also observed on the 6741W.

Frame framing and the base channels are in [PROTOCOL](PROTOCOL.md); JSON messages in [MESSAGES](MESSAGES.md).

## Channels used during a call

| Name | Notes |
|---|---|
| CTPP | call signalling and door opening during the call |
| UDPM | media control [R] |
| RTPC, RTPC2 | RTP flow; one is opened by the device toward the client [R] |

Media channels are opened like a UAUT-type channel but with a final byte (`trailing_byte`) set to 1. [R]

## Client-initiated (outbound) [R]

Sequence, for an outgoing call toward the entrance panel:

1. `call_init` CTPP `0x18C0 / 0x0028`, with a call time equal to the init time plus 1;
2. open UDPM, start the RTP receiver, two discovery packets and a keepalive every 1.5 s;
3. codec negotiation: `0x1840 / 0x0008` with parameter `0x27`, exchange and confirm;
4. open RTPC and RTPC2, `rtpc_link` `0x1840 / 0x000A` (no counter increment);
5. `VIDEO_CONFIG` `0x1840 / 0x001A` at 800x480: this is the message that starts the device's RTP flow;
6. wait for the RTPC the device opens toward us and confirm its link (with a `BYTE5` increment);
7. `HANGUP/ZERO` `0x1840 / 0x0000` starts a lease of about 30 s;
8. start the media, and optionally `answer_peer` `0x1840 / 0x0070`.

Lease renewal (~30 s, the device sends `0x1840 / 0x0003`): redo the sequence on the same TCP connection, without reconnecting.

## Incoming call (inbound) [R]

- **passive**: acknowledge the ring with a time derived from the ring time; a burst of RTPC, UDPM and codec (parameter `0x07`); `rtpc2_ready` `0x1840 / 0x0003` with flag `0x000A` (mandatory); `VIDEO_CONFIG` at 320x240. The video flows but the call is not yet answered;
- **answer**: `answer_peer` plus `call_accepted` `0x1840 / 0x0002` (roles reversed: here the client sends it). Audio (PCMA) starts on the RTPC channel the device opened.

Main differences between outgoing and incoming: codec `0x27` vs `0x07`; resolution 800x480 vs 320x240; media usually over UDP outgoing, over TCP incoming for this integration.

## Video [R] (partial [D])

- starts in SD (320x240 at 192 kbps) and, after the answer, the app switches to HD 800x480 at 1000 kbps; [D] the SD/HD switch was observed;
- the HD button toggles the two resolutions by hand, changing the preferred resolution and bitrate;
- the video is H.264. Single NALs (types 1..23, IDR 5, SPS 7, PPS 8) become Annex-B with the `00 00 00 01` prefix; FU-A fragments (type 28) are reassembled with the start and end bits and the reconstructed NAL header.

## Audio [R]

- G.711 **PCMA** (A-law), 8 kHz, 20 ms frames equal to exactly 160 bytes;
- the microphone starts muted; it is enabled with the microphone-state command;
- outgoing: timestamp +160 per frame, sequence +1 per frame, silence as the byte `0xD5` repeated.

## RTP [D]

Standard RFC 3550 header, 12 bytes, big-endian. Payload type in the second byte: `PT=8` PCMA, `PT=0` PCMU, a dynamic type for H.264. Over UDP the device sends the RTP wrapped in the ICONA framing, from which it must be extracted; over TCP it arrives already clean and starts with `0x80`.

## Exposure

Two approaches, neither included here: a local RTSP server offering H.264 and PCMA to a player such as VLC or to go2rtc, or direct consumption of the NAL and audio queues in a custom interface.

## To validate on the 6741W

Actual resolutions and bitrates, the real value of the registration-renewal increment (a wrong value silently kills events), the three CTPP timestamp regimes during a call, and the actual media capability. Until retaken on our own capture, these stay marked [R].
