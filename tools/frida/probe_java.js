// Read-only readiness probe: no credentials, hooks or control commands.
if (typeof Java === 'undefined') {
    throw new Error('Java bridge missing; use tools/frida_runner.py');
}
console.log(JSON.stringify({java_bridge_loaded: true, java_available: Java.available}));
if (Java.available) {
    Java.perform(function () {
        console.log(JSON.stringify({java_perform_ready: true}));
    });
}
