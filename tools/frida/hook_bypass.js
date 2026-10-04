// Bypass del video (che crasha il codec sotto emulazione) + mappa eventi.
// Neutralizza requestVideo/startVideo/decodeFrame; lascia vivi audio/eventi/comandi.
Java.perform(function () {
  function log(m) { console.log('[MAP] ' + m); }
  function fmt(x) {
    try {
      if (x === null || x === undefined) return String(x);
      if (typeof x !== 'string' && x.length !== undefined && typeof x.length === 'number')
        return '[' + Array.prototype.join.call(x, ',') + ']';
      var s = String(x); return s.length > 400 ? s.slice(0, 400) + '..' : s;
    } catch (e) { return '?'; }
  }

  // ---- RX: eventi ----
  try {
    var P = Java.use('com.comelitgroup.comelitvipkit.VipMessageParser');
    P.parse.overloads.forEach(function (ov) {
      ov.implementation = function (msg) { log('RX << ' + fmt(msg)); return ov.apply(this, arguments); };
    });
    log('hook parse');
  } catch (e) { log('parse err ' + e); }

  var E = Java.use('com.comelitgroup.comelitvipkit.VipEngine');

  // ---- BYPASS SOLO DEL DECODER (dove crasha il codec) ----
  // Lascio requestVideo/startVideo per la negoziazione (audio+eventi); blocco
  // solo la decodifica dei frame video, cosi' il codec nativo non gira.
  ['decodeFrame', 'getVideoFrame', 'saveFrame'].forEach(function (mn) {
    try {
      E[mn].overloads.forEach(function (ov) {
        ov.implementation = function () { return null; };
      });
    } catch (e) {}
  });
  log('DECODER video bypassato (negoziazione/audio attivi)');

  // ---- TX: comandi (log, senza toccarli) ----
  ['sendOnChannel', 'openChannel', 'closeChannel', 'answerCall', 'releaseCall',
   'generateCfp', 'createVipUnit', 'sendOpenDoorCommand', 'sendActuatorCommand',
   'sendDoorStatus', 'requestVideo', 'requestVideoKeyFrameGeneration',
   'setVipUnitBitrate', 'setVipUnitRtpMaxVideoResolution',
   'setVipUnitRtpPreferredVideoResolution', 'setVipUnitCallTimeParam'].forEach(function (mn) {
    try {
      E[mn].overloads.forEach(function (ov) {
        ov.implementation = function () {
          var a = []; for (var i = 0; i < arguments.length; i++) a.push(fmt(arguments[i]));
          log('TX> ' + mn + '(' + a.join(', ') + ')');
          return ov.apply(this, arguments);
        };
      });
    } catch (e) {}
  });

  // ---- Audio / mute (log) + startVideo neutralizzato ----
  try {
    var AV = Java.use('com.comelit.bigapp.call.manager.AudioVideoManager');
    ['start', 'startAudio', 'stop', 'stopRecording', 'startRecording',
     'setMicrophoneState', 'isAudioRunning'].forEach(function (mn) {
      try {
        AV[mn].overloads.forEach(function (ov) {
          ov.implementation = function () {
            var a = []; for (var i = 0; i < arguments.length; i++) a.push(fmt(arguments[i]));
            log('AV> ' + mn + '(' + a.join(', ') + ')');
            return ov.apply(this, arguments);
          };
        });
      } catch (e) {}
    });
    // startVideo: lascio attivo (serve alla negoziazione), solo log
    AV.startVideo.overloads.forEach(function (ov) {
      ov.implementation = function () {
        var a = []; for (var i = 0; i < arguments.length; i++) a.push(fmt(arguments[i]));
        log('AV> startVideo(' + a.join(', ') + ')');
        return ov.apply(this, arguments);
      };
    });
    log('hook AudioVideoManager');
  } catch (e) { log('AV err ' + e); }

  log('=== BYPASS+MAPPA PRONTI: reinterroga il posto esterno ===');
});
