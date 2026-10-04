<?php
/**
 * bridge.php - bacheca comandi per l'apri-porta Comelit (hosting condiviso).
 *
 * Fa da tramite fra lo Shortcut iOS (che chiede l'apertura da internet) e il
 * "postino" in casa (vecchio Android che esegue davvero l'apertura sulla LAN).
 * NON parla mai col citofono: accoda solo un comando fisso "open" e ne conserva
 * l'esito. Capacita' unica: qualunque chiamata puo' al massimo far aprire il
 * portone, niente altro.
 *
 * Azioni (parametro ?a=...):
 *   a=open    (chiave CLIENT_KEY)  -> accoda una richiesta di apertura
 *   a=status  (chiave CLIENT_KEY)  -> ultimo esito noto (per conferma sull'iPhone)
 *   a=poll    (chiave AGENT_KEY)   -> il postino preleva l'eventuale comando
 *   a=result  (chiave AGENT_KEY)   -> il postino riporta l'esito
 *
 * Sicurezza: autenticazione a token nell'header "X-Auth" (timing-safe), HTTPS
 * obbligatorio, rate limit sulle aperture, stato su file protetto da .htaccess.
 * NON mette segreti nelle risposte ne' nella URL.
 */

declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

// ---- CONFIGURAZIONE: sostituisci i due token con segreti lunghi e casuali ----
define('CLIENT_KEY', getenv('CLIENT_KEY') ?: '');
define('AGENT_KEY', getenv('AGENT_KEY') ?: '');
define('STATE_FILE', getenv('BRIDGE_STATE_FILE') ?: __DIR__ . '/bridge_state.json');
const MIN_OPEN_INTERVAL = 3;   // secondi minimi fra due aperture accettate
const JOB_TTL = 45;            // un comando non prelevato entro N s scade

function reply(int $code, array $payload): never {
    http_response_code($code);
    echo json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

function require_https(): void {
    $https = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off')
        || (getenv('TRUSTED_PROXY_IP') !== false
            && getenv('TRUSTED_PROXY_IP') === ($_SERVER['REMOTE_ADDR'] ?? '')
            && (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https'));
    if (!$https) {
        reply(400, ['status' => 'https_required']);
    }
}

function check(string $expected): void {
    if (strlen(CLIENT_KEY) < 32 || strlen(AGENT_KEY) < 32 || CLIENT_KEY === AGENT_KEY) {
        reply(503, ['status' => 'keys_not_configured']);
    }
    $given = $_SERVER['HTTP_X_AUTH'] ?? '';
    if (!is_string($given) || !hash_equals($expected, $given)) {
        reply(401, ['status' => 'unauthorized']);
    }
}

/** Carica lo stato con lock esclusivo; ritorna [handle, stato]. */
function state_open() {
    $fh = fopen(STATE_FILE . '.lock', 'c+');
    if ($fh === false) {
        reply(500, ['status' => 'state_unavailable']);
    }
    if (!flock($fh, LOCK_EX)) {
        reply(500, ['status' => 'state_lock_failed']);
    }
    if (is_file(STATE_FILE) && filesize(STATE_FILE) > 1048576) {
        reply(500, ['status' => 'state_too_large']);
    }
    $raw = is_file(STATE_FILE) ? file_get_contents(STATE_FILE) : '{}';
    $state = json_decode($raw === false ? '' : $raw, true);
    if (!is_array($state)) {
        reply(500, ['status' => 'state_corrupt']);
    }
    foreach (['pending', 'in_flight'] as $field) {
        if (isset($state[$field]) && (!is_array($state[$field])
            || !is_string($state[$field]['id'] ?? null)
            || !is_int($state[$field]['expires'] ?? null))) {
            reply(500, ['status' => 'state_schema_migration_required']);
        }
    }
    return [$fh, $state];
}

function state_save($fh, array $state): void {
    $encoded = json_encode($state, JSON_THROW_ON_ERROR);
    $temporary = tempnam(dirname(STATE_FILE), '.bridge-state-');
    if ($temporary === false) {
        reply(500, ['status' => 'state_write_failed']);
    }
    $output = fopen($temporary, 'wb');
    if ($output === false || fwrite($output, $encoded) !== strlen($encoded)
        || !fflush($output) || !fsync($output)) {
        reply(500, ['status' => 'state_write_failed']);
    }
    fclose($output);
    if (!rename($temporary, STATE_FILE)) {
        reply(500, ['status' => 'state_write_failed']);
    }
    flock($fh, LOCK_UN);
    fclose($fh);
}

require_https();
$action = $_GET['a'] ?? '';
if (!is_string($action)) {
    reply(400, ['status' => 'bad_request']);
}
$methods = ['open' => 'POST', 'poll' => 'GET', 'result' => 'POST', 'status' => 'GET'];
if (isset($methods[$action]) && ($_SERVER['REQUEST_METHOD'] ?? '') !== $methods[$action]) {
    header('Allow: ' . $methods[$action]);
    reply(405, ['status' => 'method_not_allowed']);
}

if ($action === 'open') {
    check(CLIENT_KEY);
    [$fh, $state] = state_open();
    $now = time();
    if (isset($state['in_flight'])) {
        state_save($fh, $state);
        reply(409, ['status' => 'in_flight', 'detail' => 'Check outcome; never automatically retry actuation']);
    }
    if (isset($state['pending']) && $now <= $state['pending']['expires']) {
        state_save($fh, $state);
        reply(409, ['status' => 'pending']);
    }
    if (isset($state['last_open']) && ($now - $state['last_open']) < MIN_OPEN_INTERVAL) {
        state_save($fh, $state);
        reply(429, ['status' => 'too_soon']);
    }
    // Comando FISSO: nessun parametro dal client puo' cambiare cosa viene aperto.
    $job = ['id' => bin2hex(random_bytes(8)), 'command' => 'open', 'created' => $now, 'expires' => $now + JOB_TTL];
    $state['pending'] = $job;
    $state['last_open'] = $now;
    state_save($fh, $state);
    reply(200, ['status' => 'queued', 'id' => $job['id']]);
}

if ($action === 'poll') {
    check(AGENT_KEY);
    [$fh, $state] = state_open();
    $job = $state['pending'] ?? null;
    if ($job && !isset($state['in_flight']) && time() <= $job['expires']) {
        unset($state['pending']);                 // consumo one-shot
        $state['in_flight'] = $job;
        state_save($fh, $state);
        reply(200, ['status' => 'job'] + $job);
    }
    if ($job) {                                   // scaduto: scartalo
        unset($state['pending']);
    }
    state_save($fh, $state);
    reply(200, ['status' => 'empty']);
}

if ($action === 'result') {
    check(AGENT_KEY);
    $rawBody = file_get_contents('php://input', false, null, 0, 4097);
    $body = json_decode($rawBody ?: '{}', true);
    if (strlen($rawBody ?: '') > 4096 || !is_array($body)
        || !is_string($body['id'] ?? null) || !is_string($body['outcome'] ?? null)
        || !preg_match('/^[a-f0-9]{16}$/D', $body['id'])
        || !preg_match('/^[a-z_:A-Z]{1,40}$/D', $body['outcome'])) {
        reply(400, ['status' => 'bad_request']);
    }
    [$fh, $state] = state_open();
    if (($state['in_flight']['id'] ?? null) !== $body['id']) {
        state_save($fh, $state);
        reply(409, ['status' => 'job_mismatch']);
    }
    // Conserva solo un esito sintetico (nessun segreto/token).
    $state['last_result'] = [
        'id' => (string) $body['id'],
        'outcome' => substr((string) $body['outcome'], 0, 40),
        'at' => time(),
    ];
    unset($state['in_flight']);
    state_save($fh, $state);
    reply(200, ['status' => 'recorded']);
}

if ($action === 'status') {
    check(CLIENT_KEY);
    [$fh, $state] = state_open();
    $last = $state['last_result'] ?? null;
    state_save($fh, $state);
    reply(200, ['status' => 'ok', 'last_result' => $last,
        'pending' => $state['pending'] ?? null, 'in_flight' => $state['in_flight'] ?? null]);
}

reply(404, ['status' => 'unknown_action']);
