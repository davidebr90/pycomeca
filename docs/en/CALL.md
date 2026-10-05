# Video call: signalling, video and audio

How a full call with the entrance panel works (video and two-way audio) and how the media flows. Italian version: [docs/CHIAMATA.md](../CHIAMATA.md).

This part is **not implemented** in PyCOMECA, but the **signalling** was observed in clear text on a real video call captured on the 6741W (cloud path): call start, codec, video configuration with the resolutions, and door opening during the call. The media decoding details (H.264, PCMA) remain from the 6701W reference. Evidence level:

- **[D]** observed on the 6741W (real bytes);
- **[R]** 6701W reference, not re-tested here.

The real frames (anonymised) are at the bottom, in the "Frames observed on the 6741W" section.

Frame framing and the base channels are in [PROTOCOL](PROTOCOL.md); JSON messages in [MESSAGES](MESSAGES.md).

## Channels used during a call

| Name | Notes |
|---|---|
| CTPP | call signalling and door opening during the call |
| UDPM | media control [R] |
| RTPC, RTPC2 | RTP flow; one is opened by the device toward the client [R] |

Media channels are opened like a UAUT-type channel but with a final byte (`trailing_byte`) set to 1. [R]

## Client-initiated (outbound) [D] (signalling)

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

## Incoming call (inbound) [D] signalling / [R] inbound not re-captured

- **passive**: acknowledge the ring with a time derived from the ring time; a burst of RTPC, UDPM and codec (parameter `0x07`); `rtpc2_ready` `0x1840 / 0x0003` with flag `0x000A` (mandatory); `VIDEO_CONFIG` at 320x240. The video flows but the call is not yet answered;
- **answer**: `answer_peer` plus `call_accepted` `0x1840 / 0x0002` (roles reversed: here the client sends it). Audio (PCMA) starts on the RTPC channel the device opened.

Main differences between outgoing and incoming: codec `0x27` vs `0x07`; resolution 800x480 vs 320x240; media usually over UDP outgoing, over TCP incoming for this integration.

## Video [R] (partial [D])

- starts in SD (320x240 at 192 kbps) and, after the answer, the app switches to HD 800x480 at 1000 kbps; [D] the SD/HD switch was observed;
- the HD button toggles the two resolutions by hand, changing the preferred resolution and bitrate;
- the video is H.264. Single NALs (types 1..23, IDR 5, SPS 7, PPS 8) become Annex-B with the `00 00 00 01` prefix; FU-A fragments (type 28) are reassembled with the start and end bits and the reconstructed NAL header.

## Audio [R] (not present in our capture)

From the 6701W references, not yet observed on the 6741W:

- G.711 **PCMA** (A-law), 8 kHz, 20 ms frames equal to exactly 160 bytes;
- the microphone starts muted; it is enabled with the microphone-state command;
- outgoing: timestamp +160 per frame, sequence +1 per frame, silence as the byte `0xD5` repeated.

To see it live, a call that is actually **answered** with active audio is needed: in the study capture the audio never started.

## RTP and media [partially D]

Standard RFC 3550 header, 12 bytes, big-endian. Payload type in the second byte: `PT=8` PCMA (audio), a dynamic type for H.264 (video).

What was **observed** on the 6741W, from a video-call capture on the cloud path:

- the media does NOT go over the reliable PseudoTCP stream: it travels as **raw UDP on the same ICE path**, each packet wrapped in the ICONA framing (8-byte header, then the RTP starting with `0x80`);
- **video from the device to the app**: present, with dynamic payload type `PT=99` (H.264). [D]
- **audio**: in our capture **not present** in either direction; no media went from the app to the device. The session was a one-way video call (incoming video only), typical of the emulator where the audio "answer" is not completed.

So: the media transport (ICONA over raw UDP) and the incoming video are [D]; bidirectional audio and outgoing media stay [R], to be captured on a call that is actually answered.

## Exposure

Two approaches, neither included here: a local RTSP server offering H.264 and PCMA to a player such as VLC or to go2rtc, or direct consumption of the NAL and audio queues in a custom interface.

## Frames observed on the 6741W [D]

From a real video call captured on the cloud path. Addresses anonymised (internal unit `SB000042`, entrance panel `SB100007`), counters and timestamps replaced with `..`. All on the call's CTPP channel.

`call_init` 0x18C0 / 0x0028, 72 bytes:

```
c018 ....  0028 0001  SB000042\0  SB100007\0  0001 ..........  SB000042\0  4949  ffffffff  SB100007\0  SB100007\0\0
```

`codec` 0x1840 / 0x0008, 40 bytes - the codec parameter is `0x0027`:

```
4018 ....  0008 0003 49  0027  000000 00  ffffffff  SB100007\0  SB100007\0\0
```

`VIDEO_CONFIG` 0x1840 / 0x001A, 60 bytes - it carries the two resolutions, **800x480** (0x0320 x 0x01E0) and **320x240** (0x0140 x 0x00F0):

```
4018 ....  001a 0011 1432 ........  ....  ffff 00000000  [03 20][01 e0]  [01 40][00 f0]  0010 00000000  ffffffff  SB100007\0  SB100007\0\0
```

`open during the call` 0x1840 / 0x000D, 48 bytes - a single message, param `0x002D`:

```
4018 ....  000d 002d  SB100007\0  0001 000000  ffffffff  SB100007\0  SB100007\0\0
```

`CTPP registration` 0x18C0 / 0x0011, 52 bytes, with capability `0x0040`:

```
c018 ....  0011 0040 ....  SB000042\0  100e 00000000  ffffffff  SB100007\0  SB000042\0\0
```

Also confirmed live: registration renewal 0x1860 / 0x0010, call end 0x1860 / 0x000A, `rtpc_link` 0x1840 / 0x000A, and the channel-open ACK when the device opens (`cd ab 02 00 04 00 00 00 <id> 00 00`).

## Still to validate on the 6741W

The actual bitrate (SD/HD), the real value of the registration-renewal increment (a wrong value silently kills events), and the decoding of the real media (H.264 FU-A, PCMA) stay [R] until retaken on a dedicated capture.
