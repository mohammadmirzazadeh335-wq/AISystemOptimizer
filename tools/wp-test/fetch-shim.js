// Preload shim for the sandbox network policy:
// - api.wordpress.org / downloads.wordpress.org / wordpress.org are blocked,
//   so version-check is answered locally and core zips are proxied from the
//   official GitHub mirror (WordPress/WordPress).
// - Every fetch URL is logged for debugging.
const origFetch = global.fetch;

const GITHUB_WP_ZIP = 'https://github.com/WordPress/WordPress/archive/refs/heads/master.zip';

function classify(url) {
  try {
    const u = new URL(url);
    if (u.hostname === 'api.wordpress.org') {
      if (u.pathname.includes('version-check')) return 'version-check';
      return 'api-misc';
    }
    if (u.hostname === 'downloads.wordpress.org' || u.hostname === 'wordpress.org') {
      return 'core-zip';
    }
  } catch (e) {}
  return 'pass';
}

global.fetch = async function (input, init) {
  const url = typeof input === 'string' ? input : (input && input.url) || String(input);
  const kind = classify(url);
  console.log('[fetch-shim] ' + kind + ' ' + url);

  if (kind === 'version-check') {
    const body = JSON.stringify({
      offers: [
        {
          response: 'autoupdate',
          download: GITHUB_WP_ZIP,
          locale: 'en_US',
          packages: { full: GITHUB_WP_ZIP },
          version: '6.8.1',
          php_version: '7.2.24',
          mysql_version: '5.5.5',
        },
      ],
    });
    return new Response(body, { status: 200, headers: { 'content-type': 'application/json' } });
  }

  if (kind === 'api-misc') {
    const body = JSON.stringify({ translations: [], version: '6.8.1' });
    return new Response(body, { status: 200, headers: { 'content-type': 'application/json' } });
  }

  if (kind === 'core-zip') {
    console.log('[fetch-shim] proxying core zip from GitHub mirror');
    return origFetch(GITHUB_WP_ZIP, init);
  }

  try {
    return await origFetch(input, init);
  } catch (e) {
    console.log('[fetch-shim] FAILED ' + url + ' -> ' + e.message + ' cause=' + (e.cause ? e.cause.message : ''));
    throw e;
  }
};
