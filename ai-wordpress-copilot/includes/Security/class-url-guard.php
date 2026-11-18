<?php
/**
 * SSRF protection for outbound HTTP requests.
 *
 * Validates URLs before the plugin fetches them on behalf of AI tools or the
 * link checker: scheme allow-list, IP-literal and DNS-resolved address checks
 * against private/reserved ranges (loopback, RFC1918, link-local/metadata,
 * CGNAT, multicast, IPv6 local ranges), per-hop redirect validation and
 * hardened request args for the WP HTTP API.
 *
 * @package AIWC
 */

namespace AIWC\Security;

defined( 'ABSPATH' ) || exit;

/**
 * Class Url_Guard
 */
class Url_Guard {

	/**
	 * Validate a URL for outbound fetching.
	 *
	 * @param string $url URL to validate.
	 * @return true|\WP_Error True when safe to fetch.
	 */
	public static function validate_url( $url ) {
		$url = trim( (string) $url );
		if ( '' === $url ) {
			return new \WP_Error( 'aiwc_url_empty', __( 'URL is empty.', 'ai-wordpress-copilot' ) );
		}
		if ( strlen( $url ) > 2048 ) {
			return new \WP_Error( 'aiwc_url_too_long', __( 'URL is too long.', 'ai-wordpress-copilot' ) );
		}
		$parts = wp_parse_url( $url );
		if ( ! is_array( $parts ) ) {
			return new \WP_Error( 'aiwc_url_invalid', __( 'URL could not be parsed.', 'ai-wordpress-copilot' ) );
		}

		$scheme = strtolower( isset( $parts['scheme'] ) ? (string) $parts['scheme'] : '' );
		if ( ! in_array( $scheme, array( 'http', 'https' ), true ) ) {
			return new \WP_Error(
				'aiwc_url_scheme_blocked',
				/* translators: %s: scheme name */
				sprintf( __( 'URL scheme "%s" is not allowed. Only http and https are supported.', 'ai-wordpress-copilot' ), $scheme )
			);
		}

		if ( empty( $parts['host'] ) ) {
			return new \WP_Error( 'aiwc_url_invalid', __( 'URL could not be parsed.', 'ai-wordpress-copilot' ) );
		}

		// Credentials in the authority are a phishing/smuggling vector.
		if ( isset( $parts['user'] ) || isset( $parts['pass'] ) ) {
			return new \WP_Error( 'aiwc_url_userinfo_blocked', __( 'URLs with embedded credentials are not allowed.', 'ai-wordpress-copilot' ) );
		}

		$host = strtolower( (string) $parts['host'] );
		$port = isset( $parts['port'] ) ? (int) $parts['port'] : 0;

		// Explicit host allow-list (filterable; test environments and intranets).
		$allowed = (array) apply_filters( 'aiwc_url_guard_allowed_hosts', array() );
		$allowed = array_map( 'strtolower', $allowed );
		if ( in_array( $host, $allowed, true ) || in_array( $host . ':' . $port, $allowed, true ) ) {
			return true;
		}

		// IP-literal hosts: strict range checks, always enforced.
		$ip = trim( $host, '[]' ); // IPv6 literals arrive bracketed.
		if ( self::is_ip_address( $ip ) ) {
			if ( self::is_ip_blocked( $ip ) ) {
				return new \WP_Error(
					'aiwc_url_private_ip',
					__( 'URLs resolving to private, loopback or reserved IP addresses are not allowed.', 'ai-wordpress-copilot' )
				);
			}
			return true;
		}

		// Hostnames: resolve and verify every returned address. Test/proxy
		// environments can skip the resolved-IP privacy check via a filter
		// (IP literals above remain strictly checked).
		$trust_dns = (bool) apply_filters( 'aiwc_url_guard_trust_dns', false );
		if ( $trust_dns ) {
			return true;
		}

		$ips = self::resolve_host( $host );
		if ( empty( $ips ) ) {
			// Resolution failed: refuse (fail closed).
			return new \WP_Error(
				'aiwc_url_dns_failed',
				__( 'The URL host could not be resolved.', 'ai-wordpress-copilot' )
			);
		}
		foreach ( $ips as $resolved ) {
			if ( self::is_ip_blocked( $resolved ) ) {
				return new \WP_Error(
					'aiwc_url_private_ip',
					__( 'URLs resolving to private, loopback or reserved IP addresses are not allowed.', 'ai-wordpress-copilot' )
				);
			}
		}
		return true;
	}

	/**
	 * Is the given string an IP address?
	 *
	 * @param string $value Value to test.
	 * @return bool
	 */
	public static function is_ip_address( $value ) {
		return (bool) filter_var( $value, FILTER_VALIDATE_IP );
	}

	/**
	 * Block private/reserved/loopback/link-local IP addresses.
	 *
	 * @param string $ip IP address.
	 * @return bool True when the address must not be fetched.
	 */
	public static function is_ip_blocked( $ip ) {
		$ip = trim( (string) $ip, '[]' );
		if ( ! self::is_ip_address( $ip ) ) {
			return true; // Not an IP at all: treat as unsafe here.
		}

		// IPv4-mapped IPv6 (::ffff:a.b.c.d) — check the embedded IPv4.
		if ( false !== strpos( $ip, '.' ) && false !== strpos( $ip, ':' ) ) {
			$embedded = substr( $ip, strrpos( $ip, ':' ) + 1 );
			if ( self::is_ip_address( $embedded ) ) {
				$ip = $embedded;
			}
		}

		if ( filter_var( $ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4 ) ) {
			$blocked = array(
				'0.0.0.0/8',       // "This" network.
				'10.0.0.0/8',      // RFC1918.
				'100.64.0.0/10',   // CGNAT.
				'127.0.0.0/8',     // Loopback.
				'169.254.0.0/16',  // Link-local / cloud metadata (169.254.169.254).
				'172.16.0.0/12',   // RFC1918.
				'192.0.0.0/24',    // IETF protocol assignments.
				'192.0.2.0/24',    // TEST-NET-1.
				'192.88.99.0/24',  // 6to4 relay anycast.
				'192.168.0.0/16',  // RFC1918.
				'198.18.0.0/15',   // Benchmarking.
				'198.51.100.0/24', // TEST-NET-2.
				'203.0.113.0/24',  // TEST-NET-3.
				'224.0.0.0/4',     // Multicast.
				'240.0.0.0/4',     // Reserved + broadcast.
			);
			foreach ( $blocked as $cidr ) {
				if ( self::ipv4_in_cidr( $ip, $cidr ) ) {
					return true;
				}
			}
			return false;
		}

		// IPv6.
		$packed = @inet_pton( $ip );
		if ( false === $packed || 16 !== strlen( $packed ) ) {
			return true;
		}
		$blocked_v6 = array(
			'::1/128',        // Loopback.
			'::/128',         // Unspecified.
			'fc00::/7',       // Unique local.
			'fe80::/10',      // Link-local.
			'ff00::/8',       // Multicast.
			'2001:db8::/32',  // Documentation.
			'64:ff9b:1::/48', // Local-use NAT64.
			'2002::/16',      // 6to4 (embeds IPv4 — conservatively blocked).
		);
		foreach ( $blocked_v6 as $cidr ) {
			if ( self::ipv6_in_cidr( $ip, $cidr ) ) {
				return true;
			}
		}
		return false;
	}

	/**
	 * Resolve a hostname to all IPv4/IPv6 addresses.
	 *
	 * @param string $host Hostname.
	 * @return string[] Addresses (possibly empty).
	 */
	public static function resolve_host( $host ) {
		$ips = array();
		if ( function_exists( 'gethostbynamel' ) ) {
			$v4 = @gethostbynamel( $host ); // phpcs:ignore WordPress.PHP.NoSilencedErrors
			if ( is_array( $v4 ) ) {
				$ips = array_merge( $ips, $v4 );
			}
		}
		if ( function_exists( 'dns_get_record' ) ) {
			$records = @dns_get_record( $host, DNS_AAAA ); // phpcs:ignore WordPress.PHP.NoSilencedErrors
			if ( is_array( $records ) ) {
				foreach ( $records as $rec ) {
					if ( ! empty( $rec['ipv6'] ) ) {
						$ips[] = $rec['ipv6'];
					}
				}
			}
		}
		return array_values( array_unique( $ips ) );
	}

	/**
	 * Hardened WP HTTP API args for outbound fetches (no auto redirects).
	 *
	 * @param array $args Base args.
	 * @return array
	 */
	public static function safe_http_args( array $args = array() ) {
		return array_merge(
			array(
				'redirection' => 0, // Redirects are followed manually with validation.
				'timeout'     => 10,
				'sslverify'   => true,
			),
			$args
		);
	}

	/**
	 * Fetch a URL with per-hop redirect validation (SSRF-safe).
	 *
	 * @param string $url           URL.
	 * @param array  $args          wp_remote_get args.
	 * @param int    $max_redirects Maximum redirect hops.
	 * @return array{response: array|WP_Error, redirects: string[], final_url: string}
	 */
	public static function request_with_validated_redirects( $url, array $args = array(), $max_redirects = 5 ) {
		$redirects = array();
		$current   = $url;
		for ( $hop = 0; $hop <= max( 0, $max_redirects ); $hop++ ) {
			$check = self::validate_url( $current );
			if ( is_wp_error( $check ) ) {
				return array(
					'response'   => $check,
					'redirects'  => $redirects,
					'final_url'  => $current,
				);
			}
			// The Url_Guard above is the authority (wp_safe_remote_get would
			// also block filter-allowlisted test/intranet hosts).
			$response = wp_remote_get( $current, self::safe_http_args( $args ) );
			$code = is_wp_error( $response ) ? 0 : (int) wp_remote_retrieve_response_code( $response );
			if ( $code >= 300 && $code < 400 ) {
				$location = wp_remote_retrieve_header( $response, 'location' );
				$location = is_array( $location ) ? (string) reset( $location ) : (string) $location;
				if ( '' === $location ) {
					return array(
						'response'  => $response,
						'redirects' => $redirects,
						'final_url' => $current,
					);
				}
				// Resolve relative redirects against the current URL; the loop
				// head validates every hop before it is fetched.
				$next = trim( $location );
				if ( ! parse_url( $next, PHP_URL_HOST ) ) {
					$scheme = (string) wp_parse_url( $current, PHP_URL_SCHEME );
					$host   = (string) wp_parse_url( $current, PHP_URL_HOST );
					$port   = wp_parse_url( $current, PHP_URL_PORT );
					$prefix = $scheme . '://' . $host . ( $port ? ':' . $port : '' );
					$next   = 0 === strpos( $next, '/' ) ? $prefix . $next : $prefix . '/' . $next;
				}
				$redirects[] = $next;
				$current     = $next;
				continue;
			}
			return array(
				'response'  => $response,
				'redirects' => $redirects,
				'final_url' => $current,
			);
		}
		return array(
			'response'  => new \WP_Error( 'aiwc_too_many_redirects', __( 'Too many redirects.', 'ai-wordpress-copilot' ) ),
			'redirects' => $redirects,
			'final_url' => $current,
		);
	}

	/**
	 * IPv4 in CIDR check.
	 *
	 * @param string $ip   IPv4 address.
	 * @param string $cidr CIDR.
	 * @return bool
	 */
	private static function ipv4_in_cidr( $ip, $cidr ) {
		list( $subnet, $bits ) = array_pad( explode( '/', $cidr ), 2, 32 );
		$bits  = (int) $bits;
		$ip_n  = ip2long( $ip );
		$sub_n = ip2long( $subnet );
		if ( false === $ip_n || false === $sub_n ) {
			return true; // Fail closed on parse problems.
		}
		$mask = -1 << ( 32 - $bits );
		return ( $ip_n & $mask ) === ( $sub_n & $mask );
	}

	/**
	 * IPv6 in CIDR check.
	 *
	 * @param string $ip   IPv6 address.
	 * @param string $cidr CIDR.
	 * @return bool
	 */
	private static function ipv6_in_cidr( $ip, $cidr ) {
		list( $subnet, $bits ) = array_pad( explode( '/', $cidr ), 2, 128 );
		$bits = (int) $bits;
		$ip_b  = @inet_pton( $ip );      // phpcs:ignore WordPress.PHP.NoSilencedErrors
		$sub_b = @inet_pton( $subnet );  // phpcs:ignore WordPress.PHP.NoSilencedErrors
		if ( false === $ip_b || false === $sub_b ) {
			return true; // Fail closed.
		}
		$bytes = intdiv( $bits, 8 );
		$rem   = $bits % 8;
		if ( $bytes > 0 && substr( $ip_b, 0, $bytes ) !== substr( $sub_b, 0, $bytes ) ) {
			return false;
		}
		if ( $rem > 0 ) {
			$mask = chr( ( 0xFF << ( 8 - $rem ) ) & 0xFF );
			if ( ( $ip_b[ $bytes ] & $mask ) !== ( $sub_b[ $bytes ] & $mask ) ) {
				return false;
			}
		}
		return true;
	}
}
