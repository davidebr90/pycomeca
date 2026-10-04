// Indagine MQTT: aggancia il client Paho + i comandi VIP, per capire se il
// messaggio "access" (apertura) passa su MQTT in chiaro o incapsulato nel P2P.
Java.perform(function () {
  function log(m) { console.log('[VIP] ' + m); }
  function fmt(x) {
    try {
      if (x === null || x === undefined) return String(x);
      if (typeof x !== 'string' && x.length !== undefined && typeof x.length === 'number')
        return '[' + Array.prototype.join.call(x, ',') + ']';
      return String(x);
    } catch (e) { return '?'; }
  }
  function bytesToStr(b) {
    if (!b) return 'null';
    try {
      var printable = true, s = '';
      for (var i = 0; i < b.length; i++) {
        var c = b[i] & 0xff;
        if (c === 9 || c === 10 || c === 13 || (c >= 32 && c < 127)) s += String.fromCharCode(c);
        else { printable = false; break; }
      }
      if (printable) return 'STR(' + b.length + '): ' + s;
      var h = '';
      for (var i = 0; i < Math.min(b.length, 120); i++) h += ('0' + (b[i] & 0xff).toString(16)).slice(-2);
      return 'HEX(' + b.length + '): ' + h + (b.length > 120 ? '...' : '');
    } catch (e) { return '?'; }
  }

  // --- comandi VIP chiave (per correlare) ---
  try {
    var E = Java.use('com.comelitgroup.comelitvipkit.VipEngine');
    ['sendOpenDoorCommand', 'sendOnChannel', 'openChannel', 'closeChannel', 'sendActuatorCommand'].forEach(function (mn) {
      try {
        E[mn].overloads.forEach(function (ov) {
          ov.implementation = function () {
            var a = []; for (var i = 0; i < arguments.length; i++) a.push(fmt(arguments[i]));
            log('>>> VipEngine.' + mn + '(' + a.join(', ') + ')');
            return ov.apply(this, arguments);
          };
        });
      } catch (e) {}
    });
    log('hook VipEngine ok');
  } catch (e) { log('VipEngine err ' + e); }

  // --- MQTT Paho: connect / publish / subscribe ---
  function hookMqtt(clsName) {
    var C;
    try { C = Java.use(clsName); } catch (e) { return false; }
    // publish
    try {
      C.publish.overloads.forEach(function (ov) {
        ov.implementation = function () {
          try {
            var topic = arguments.length ? String(arguments[0]) : '?';
            var payloadStr = '';
            for (var i = 1; i < arguments.length; i++) {
              var arg = arguments[i];
              if (arg && arg.getPayload) { try { payloadStr = bytesToStr(arg.getPayload()); break; } catch (e) {} }
              if (arg && typeof arg !== 'string' && arg.length !== undefined) { payloadStr = bytesToStr(arg); break; }
            }
            log('### MQTT PUBLISH topic=' + topic + ' payload=' + payloadStr);
          } catch (e) { log('mqtt pub log err ' + e); }
          return ov.apply(this, arguments);
        };
      });
    } catch (e) {}
    // connect
    try {
      C.connect.overloads.forEach(function (ov) {
        ov.implementation = function () {
          try { log('### MQTT CONNECT server=' + (this.getServerURI ? this.getServerURI() : '?')); } catch (e) {}
          return ov.apply(this, arguments);
        };
      });
    } catch (e) {}
    // subscribe
    try {
      C.subscribe.overloads.forEach(function (ov) {
        ov.implementation = function () {
          try { log('### MQTT SUBSCRIBE topic=' + fmt(arguments[0])); } catch (e) {}
          return ov.apply(this, arguments);
        };
      });
    } catch (e) {}
    log('hook MQTT ok: ' + clsName);
    return true;
  }
  ['org.eclipse.paho.client.mqttv3.MqttAsyncClient',
   'org.eclipse.paho.client.mqttv3.MqttClient'].forEach(hookMqtt);

  log('=== HOOK MQTT+VIP PRONTI: rifai interroga posto esterno + apri ===');
});
