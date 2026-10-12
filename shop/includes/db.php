<?php
// Supabase REST (PostgREST) helper. Service (secret) key, JSON, curl. Used everywhere.
// Filters are passed as arrays, e.g. ['username' => 'eq.kamal'], and are URL-encoded here.

class SbError extends Exception {
    public $status;
    public $body;
    public function __construct(string $msg, int $status = 0, $body = null) {
        parent::__construct($msg);
        $this->status = $status;
        $this->body = $body;
    }
}

function sb_request(string $method, string $path, array $query = [], $body = null, array $extra = []): array {
    $base = rtrim((string)env('SUPABASE_URL', ''), '/');
    $key = (string)env('SUPABASE_SECRET_KEY', '');
    if ($base === '' || $key === '') throw new SbError('Supabase is not configured', 0);
    $url = $base . '/rest/v1/' . $path;
    if ($query) $url .= '?' . http_build_query($query, '', '&', PHP_QUERY_RFC3986);
    $headers = ['apikey: ' . $key, 'Authorization: Bearer ' . $key,
                'Content-Type: application/json', 'Accept: application/json'];
    foreach ($extra as $hd) $headers[] = $hd;
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_TIMEOUT => 20,
        CURLOPT_CONNECTTIMEOUT => 10,
    ]);
    if ($body !== null) {
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($body, JSON_INVALID_UTF8_SUBSTITUTE));
    }
    $resp = curl_exec($ch);
    $err = curl_error($ch);
    $status = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    if ($resp === false) throw new SbError('Database connection failed: ' . $err, 0);
    $data = ($resp === '') ? null : json_decode($resp, true);
    return [$status, $data];
}

function sb_select(string $table, array $query = []): array {
    [$s, $d] = sb_request('GET', $table, $query);
    if ($s >= 300) throw new SbError("select $table failed ($s)", $s, $d);
    return is_array($d) ? $d : [];
}

// $rows: one assoc row, or a list of rows. Returns the inserted rows.
function sb_insert(string $table, array $rows): array {
    [$s, $d] = sb_request('POST', $table, [], $rows, ['Prefer: return=representation']);
    if ($s >= 300) throw new SbError("insert $table failed ($s)", $s, $d);
    return is_array($d) ? $d : [];
}

function sb_update(string $table, array $filters, array $patch): array {
    [$s, $d] = sb_request('PATCH', $table, $filters, $patch, ['Prefer: return=representation']);
    if ($s >= 300) throw new SbError("update $table failed ($s)", $s, $d);
    return is_array($d) ? $d : [];
}

function sb_delete(string $table, array $filters): void {
    [$s, $d] = sb_request('DELETE', $table, $filters);
    if ($s >= 300) throw new SbError("delete $table failed ($s)", $s, $d);
}

function sb_rpc(string $fn, array $args) {
    [$s, $d] = sb_request('POST', 'rpc/' . $fn, [], $args);
    if ($s >= 300) throw new SbError("rpc $fn failed ($s)", $s, $d);
    return $d;
}
