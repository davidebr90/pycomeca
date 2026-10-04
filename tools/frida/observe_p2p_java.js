// Passive Java observer: method names and safe transport metadata only.
Java.perform(function () {
    const Engine = Java.use('com.comelitgroup.comelitvipkit.VipEngine');
    const emit = value => console.log(JSON.stringify({at_ms: Date.now(), ...value}));
    ['createViperTunnel', 'openChannel', 'closeChannel', 'sendOnChannel',
     'sendOpenDoorCommand', 'sendActuatorCommand'].forEach(name => {
        Engine[name].overloads.forEach(overload => {
            overload.implementation = function () {
                const record = {event: name, arguments: arguments.length};
                if (name === 'createViperTunnel') {
                    record.transport = arguments.length === 2 ? 'p2p_parameters' : 'direct_parameters';
                }
                if (name === 'openChannel' || name === 'closeChannel' || name === 'sendOnChannel') {
                    record.channel_type = arguments[1];
                }
                emit(record);
                const result = overload.apply(this, arguments);
                if (name === 'createViperTunnel') emit({event: 'tunnel_result', transport: record.transport, result: Number(result)});
                return result;
            };
        });
    });
    emit({event: 'ready', java: true});
});
