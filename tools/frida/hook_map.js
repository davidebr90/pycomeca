// MAPPA COMPLETA eventi/comandi VIP.
// RX = messaggi ricevuti (VipMessageParser.parse). TX = comandi inviati
// (VipEngine + AudioVideoManager). Esclusi i metodi media ad alta frequenza.
Java.perform(function () {
  function log(m) { console.log('[MAP] ' + m); }
  function fmt(x) {
    try {
      if (x === null || x === undefined) return String(x);
      if (typeof x !== 'string' && x.length !== undefined && typeof x.length === 'number')
        return '[' + Array.prototype.join.call(x, ',') + ']';
      var s = String(x);
      return s.length > 400 ? s.slice(0, 400) + '..' : s;
    } catch (e) { return '?'; }
  }
  function hookList(clsName, methods, tag) {
    var cls;
    try { cls = Java.use(clsName); } catch (e) { log('assente: ' + clsName); return; }
    var n = 0;
    methods.forEach(function (mn) {
      var ovs; try { ovs = cls[mn].overloads; } catch (e) { return; }
      if (!ovs) return;
      ovs.forEach(function (ov) {
        try {
          ov.implementation = function () {
            var a = []; for (var i = 0; i < arguments.length; i++) a.push(fmt(arguments[i]));
            log(tag + ' ' + mn + '(' + a.join(', ') + ')');
            return ov.apply(this, arguments);
          };
        } catch (e) {}
      });
      n++;
    });
    log('hook ' + clsName.split('.').pop() + ' (' + n + ' metodi)');
  }

  // RX: tutti i messaggi in ingresso
  try {
    var P = Java.use('com.comelitgroup.comelitvipkit.VipMessageParser');
    P.parse.overloads.forEach(function (ov) {
      ov.implementation = function (msg) {
        log('RX << ' + fmt(msg));
        return ov.apply(this, arguments);
      };
    });
    log('hook VipMessageParser.parse (RX)');
  } catch (e) { log('parse err ' + e); }

  // TX: comandi VIP (esclusi getVideoFrame/getAudioPacket/decodeFrame/addReceivedPacketFromSocket/isOnSource/saveFrame/getStreamInfo)
  hookList('com.comelitgroup.comelitvipkit.VipEngine', [
    'sendOnChannel', 'openChannel', 'closeChannel', 'requestVideo', 'requestVideoKeyFrameGeneration',
    'answerCall', 'releaseCall', 'generateCfp', 'createVipUnit', 'removeVipUnit', 'removeSystem',
    'sendOpenDoorCommand', 'sendActuatorCommand', 'sendDoorStatus',
    'setVipUnitBitrate', 'setVipUnitRtpMaxVideoResolution', 'setVipUnitRtpPreferredVideoResolution',
    'setVipUnitCallTimeParam', 'createViperTunnel'
  ], 'TX>');

  // TX: audio/video/mute lato app
  hookList('com.comelit.bigapp.call.manager.AudioVideoManager', [
    'start', 'startVideo', 'startAudio', 'stop', 'stopRecording', 'startRecording',
    'setMicrophoneState', 'isAudioRunning'
  ], 'AV>');

  log('=== MAPPA EVENTI PRONTA: esegui le azioni nellapp una per una ===');
});
