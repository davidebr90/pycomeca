// Chiamata ENTRANTE dal posto esterno: push FCM + flusso incoming + mappa.
// Mantiene il bypass del decoder video (per non crashare alla risposta).
Java.perform(function () {
  function log(m) { console.log('[MAP] ' + m); }
  function fmt(x) {
    try {
      if (x === null || x === undefined) return String(x);
      if (typeof x !== 'string' && x.length !== undefined && typeof x.length === 'number')
        return '[' + Array.prototype.join.call(x, ',') + ']';
      var s = String(x); return s.length > 500 ? s.slice(0, 500) + '..' : s;
    } catch (e) { return '?'; }
  }
  function hookList(clsName, methods, tag) {
    var cls; try { cls = Java.use(clsName); } catch (e) { log('assente: ' + clsName); return; }
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
    });
    log('hook ' + clsName.split('.').pop());
  }
  function hookAll(clsName, tag, skip) {
    var cls; try { cls = Java.use(clsName); } catch (e) { log('assente: ' + clsName); return; }
    var names = {};
    try { cls.class.getDeclaredMethods().forEach(function (m) { names[m.getName()] = true; }); }
    catch (e) { return; }
    Object.keys(names).forEach(function (mn) {
      if (skip && skip.indexOf(mn) >= 0) return;
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
    });
    log('hookAll ' + clsName.split('.').pop() + ' (' + Object.keys(names).length + ')');
  }

  // --- bypass decoder video ---
  try {
    var E = Java.use('com.comelitgroup.comelitvipkit.VipEngine');
    ['decodeFrame', 'getVideoFrame', 'saveFrame'].forEach(function (mn) {
      try { E[mn].overloads.forEach(function (ov) { ov.implementation = function () { return null; }; }); } catch (e) {}
    });
    log('decoder video bypassato');
  } catch (e) {}

  // --- RX eventi ---
  try {
    Java.use('com.comelitgroup.comelitvipkit.VipMessageParser').parse.overloads.forEach(function (ov) {
      ov.implementation = function (msg) { log('RX << ' + fmt(msg)); return ov.apply(this, arguments); };
    });
    log('hook parse (RX)');
  } catch (e) {}

  // --- PUSH FCM in ingresso (la notifica che avvisa della chiamata) ---
  try {
    var FMS = Java.use('com.comelit.bigapp.notification.ComelitFirebaseMessagingService');
    FMS.onMessageReceived.overloads.forEach(function (ov) {
      ov.implementation = function (rm) {
        try {
          var data = rm.getData ? rm.getData() : null;
          log('PUSH << from=' + (rm.getFrom ? rm.getFrom() : '?') + ' data=' + fmt(data));
        } catch (e) { log('PUSH << (parse err ' + e + ')'); }
        return ov.apply(this, arguments);
      };
    });
    log('hook ComelitFirebaseMessagingService.onMessageReceived');
  } catch (e) { log('FMS err ' + e); }

  // --- TX comandi VIP (per la risposta/apertura da chiamata) ---
  hookList('com.comelitgroup.comelitvipkit.VipEngine', [
    'sendOnChannel', 'openChannel', 'closeChannel', 'answerCall', 'releaseCall',
    'generateCfp', 'createVipUnit', 'sendOpenDoorCommand', 'sendActuatorCommand',
    'requestVideo', 'setVipUnitBitrate', 'setVipUnitRtpPreferredVideoResolution'
  ], 'TX>');

  // --- audio/mute ---
  hookList('com.comelit.bigapp.call.manager.AudioVideoManager',
    ['start', 'startVideo', 'startAudio', 'stop', 'setMicrophoneState'], 'AV>');

  // --- flusso incoming-call SDK + notifica ---
  hookAll('com.comelit.bigapp.call.NotificationCenter', 'NOTIF>',
    ['notificationManager_delegate$lambda$0']);
  hookAll('com.comelitgroup.sdk.incomingcall.CallService', 'CALLSVC>');
  hookAll('com.comelitgroup.sdk.incomingcall.CallConnection', 'CALLCONN>');
  hookAll('com.comelitgroup.sdk.incomingcall.CallRinger', 'RINGER>');
  hookAll('com.comelitgroup.sdk.incomingcall.CallRegistry', 'CALLREG>');
  hookAll('com.comelitgroup.sdk.incomingcall.CallNotificationHandler', 'NHANDLER>');

  log('=== INCOMING PRONTO: scendi e premi il tasto chiamata sul posto esterno ===');
});
