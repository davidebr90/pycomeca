"""Remote (cloud P2P viper_p2p_v2) transport for the ICONA session.

Independent client re-implementation of the transport the official app uses to
reach the MSVF from outside the LAN: p2p/start SDP exchange, ICE connectivity,
and a libnice-compatible PseudoTCP reliable stream. On top of that stream the
existing synchronous ICONA client (`pycomeca.client.IconaClient`) runs unchanged.

Pure standard library. This package is optional and isolated: importing
`pycomeca` core never imports it, so the local path keeps zero dependencies.

Wire formats are pinned against real captures (docs/REMOTE_P2P.md and the
ICE verify pcap). Nothing here has yet been proven end-to-end against the live
device; the modules are unit-tested offline. See docs/REMOTE_P2P.md §5.
"""
