<?php
/**
 * Central design system: colors, typography, radii, shadows, spacing,
 * container, button styles and breakpoints — detected from the active
 * builder (Elementor > Gutenberg > theme) and applied everywhere.
 *
 * @package AIWC
 */

namespace AIWC\Builder;

defined( 'ABSPATH' ) || exit;

/**
 * Class Design_System
 */
class Design_System {

	const OPTION = 'aiwc_design_system';

	/**
	 * Default tokens (kept minimal and tasteful; full set is filterable).
	 *
	 * @return array
	 */
	public static function defaults() {
		return array(
			'colors'     => array(
				'primary'   => '#2563eb',
				'secondary' => '#1e40af',
				'accent'    => '#f59e0b',
				'text'      => '#1f2937',
				'muted'     => '#6b7280',
				'bg'        => '#ffffff',
				'surface'   => '#f3f4f6',
			),
			'typography' => array(
				'body_font'    => 'system-ui, -apple-system, "Segoe UI", sans-serif',
				'heading_font' => 'system-ui, -apple-system, "Segoe UI", sans-serif',
				'base_size'    => '16px',
				'h1_size'      => '2.5rem',
				'h2_size'      => '2rem',
				'h3_size'      => '1.5rem',
				'h4_size'      => '1.25rem',
				'weight_body'  => 400,
				'weight_heading' => 700,
				'line_height'  => 1.7,
			),
			'radius'     => array(
				'sm' => '6px',
				'md' => '12px',
				'lg' => '20px',
			),
			'shadows'    => array(
				'sm' => '0 1px 2px rgba(0,0,0,0.06)',
				'md' => '0 4px 12px rgba(0,0,0,0.10)',
				'lg' => '0 12px 32px rgba(0,0,0,0.14)',
			),
			'spacing'    => array(
				'xs' => '4px',
				'sm' => '8px',
				'md' => '16px',
				'lg' => '32px',
				'xl' => '64px',
			),
			'container'  => array(
				'width'   => '1200px',
				'padding' => '24px',
			),
			'buttons'    => array(
				'radius'     => '12px',
				'padding_x'  => '24px',
				'padding_y'  => '12px',
				'weight'     => 600,
				'primary_bg' => '', // Empty = colors.primary.
			),
			'breakpoints' => array(
				'mobile'  => '640px',
				'tablet'  => '1024px',
			),
		);
	}

	/**
	 * Get the stored design system (merged with defaults).
	 *
	 * @return array
	 */
	public static function get() {
		$stored = get_option( self::OPTION, array() );
		if ( ! is_array( $stored ) ) {
			$stored = array();
		}
		return self::merge( self::defaults(), $stored );
	}

	/**
	 * Deep merge (values win over defaults).
	 *
	 * @param array $base Base.
	 * @param array $over Overrides.
	 * @return array
	 */
	private static function merge( array $base, array $over ) {
		foreach ( $over as $k => $v ) {
			if ( is_array( $v ) && isset( $base[ $k ] ) && is_array( $base[ $k ] ) ) {
				$base[ $k ] = self::merge( $base[ $k ], $v );
			} else {
				$base[ $k ] = $v;
			}
		}
		return $base;
	}

	/**
	 * Validate + save a partial update (natural-language edits arrive here as
	 * explicit tokens chosen by the model).
	 *
	 * @param array $patch Partial token set.
	 * @return array The saved system.
	 */
	public static function update( array $patch ) {
		$clean = self::sanitize( $patch );
		$next  = self::merge( self::get(), $clean );
		update_option( self::OPTION, $next, false );
		do_action( 'aiwc_design_system_updated', $next );
		return $next;
	}

	/**
	 * Sanitize incoming tokens (scalars, safe CSS values only).
	 *
	 * @param array $patch Patch.
	 * @return array
	 */
	private static function sanitize( array $patch ) {
		$out = array();
		foreach ( $patch as $group => $values ) {
			if ( ! is_array( $values ) ) {
				continue;
			}
			foreach ( $values as $key => $value ) {
				if ( ! is_scalar( $value ) ) {
					continue;
				}
				$value = trim( (string) $value );
				if ( '' === $value ) {
					continue;
				}
				// Allow colors, sizes, fonts, numbers, weights — nothing else.
				if ( ! preg_match( '/^[#a-zA-Z0-9_,.\'\"() %:\-\/]+$/', $value ) ) {
					continue;
				}
				if ( strlen( $value ) > 200 ) {
					$value = substr( $value, 0, 200 );
				}
				$out[ $group ][ $key ] = is_numeric( $value ) && ! preg_match( '/px|rem|em|%|vh|vw/', $value ) ? ( 0 === strpos( $value, '0' ) && strlen( $value ) > 1 && '0' !== $value[1] ? $value : +$value ) : $value;
			}
		}
		return $out;
	}

	/**
	 * Detect tokens from the environment with priority
	 * Elementor > Gutenberg Global Styles > active theme.
	 *
	 * @return array{tokens: array, source: string}
	 */
	public static function detect() {
		// 1) Elementor global kit.
		if ( did_action( 'elementor/loaded' ) || defined( 'ELEMENTOR_VERSION' ) ) {
			$kit_id = (int) get_option( 'elementor_active_kit' );
			$kit    = $kit_id ? get_post_meta( $kit_id, '_elementor_page_settings', true ) : '';
			$kit    = is_string( $kit ) ? json_decode( $kit, true ) : $kit;
			if ( is_array( $kit ) && ! empty( $kit['system_colors'] ) ) {
				$colors = array();
				foreach ( $kit['system_colors'] as $sc ) {
					$id = isset( $sc['_id'] ) ? (string) $sc['_id'] : '';
					$val = isset( $sc['color'] ) ? (string) $sc['color'] : '';
					if ( '' === $val ) {
						continue;
					}
					if ( false !== strpos( $id, 'primary' ) ) {
						$colors['primary'] = $val;
					} elseif ( false !== strpos( $id, 'secondary' ) ) {
						$colors['secondary'] = $val;
					} elseif ( false !== strpos( $id, 'accent' ) || false !== strpos( $id, 'text' ) ) {
						$colors[ false !== strpos( $id, 'text' ) ? 'text' : 'accent' ] = $val;
					} elseif ( false !== strpos( $id, 'background' ) ) {
						$colors['bg'] = $val;
					}
				}
				$tokens = self::merge( self::defaults(), array( 'colors' => $colors ) );
				return array( 'tokens' => $tokens, 'source' => 'elementor' );
			}
		}

		// 2) Gutenberg global styles (block themes).
		if ( function_exists( 'wp_get_global_styles' ) && wp_is_block_theme() ) {
			$gs = wp_get_global_styles();
			if ( is_array( $gs ) ) {
				$colors = array();
				if ( ! empty( $gs['color']['palette']['theme'][0]['color'] ) ) {
					$colors['primary'] = (string) $gs['color']['palette']['theme'][0]['color'];
				}
				if ( ! empty( $gs['color']['background'] ) ) {
					$colors['bg'] = (string) $gs['color']['background'];
				}
				if ( ! empty( $gs['color']['text'] ) ) {
					$colors['text'] = (string) $gs['color']['text'];
				}
				$typo = array();
				if ( ! empty( $gs['typography']['fontFamily'] ) ) {
					$typo['body_font'] = (string) $gs['typography']['fontFamily'];
					$typo['heading_font'] = (string) $gs['typography']['fontFamily'];
				}
				$tokens = self::merge( self::defaults(), array( 'colors' => $colors, 'typography' => $typo ) );
				return array( 'tokens' => $tokens, 'source' => 'gutenberg' );
			}
		}

		// 3) Active theme mods (best effort).
		$colors = array();
		$primary = get_theme_mod( 'primary_color' );
		if ( $primary ) {
			$colors['primary'] = (string) $primary;
		}
		$bg = get_theme_mod( 'background_color' );
		if ( $bg ) {
			$colors['bg'] = 0 === strpos( (string) $bg, '#' ) ? (string) $bg : '#' . (string) $bg;
		}
		$tokens = self::merge( self::defaults(), array( 'colors' => $colors ) );
		return array( 'tokens' => $tokens, 'source' => 'theme' );
	}

	/**
	 * Apply the current system to the environment:
	 * - Block themes: Global Styles (palette + typography).
	 * - All sites: generated CSS variables appended to the custom stylesheet.
	 *
	 * @param array|null $system System (default: current).
	 * @return array{global_styles: bool, css_vars: bool}
	 */
	public static function apply( $system = null ) {
		$system = $system ? $system : self::get();
		$applied = array( 'global_styles' => false, 'css_vars' => false );

		// Global Styles palette for block themes.
		if ( function_exists( 'wp_update_global_styles' ) && wp_is_block_theme() ) {
			$gs = wp_get_global_styles();
			if ( ! is_array( $gs ) ) {
				$gs = array();
			}
			$gs['color'] = isset( $gs['color'] ) && is_array( $gs['color'] ) ? $gs['color'] : array();
			$gs['color']['palette'] = array(
				'theme' => array(
					array( 'slug' => 'primary', 'color' => $system['colors']['primary'], 'name' => 'Primary' ),
					array( 'slug' => 'secondary', 'color' => $system['colors']['secondary'], 'name' => 'Secondary' ),
					array( 'slug' => 'accent', 'color' => $system['colors']['accent'], 'name' => 'Accent' ),
					array( 'slug' => 'contrast', 'color' => $system['colors']['text'], 'name' => 'Text' ),
					array( 'slug' => 'base', 'color' => $system['colors']['bg'], 'name' => 'Background' ),
					array( 'slug' => 'surface', 'color' => $system['colors']['surface'], 'name' => 'Surface' ),
				),
			);
			$gs['color']['background'] = $system['colors']['bg'];
			$gs['color']['text']       = $system['colors']['text'];
			$gs['typography']          = isset( $gs['typography'] ) && is_array( $gs['typography'] ) ? $gs['typography'] : array();
			$gs['typography']['fontFamily'] = $system['typography']['body_font'];
			$gs['typography']['lineHeight'] = (string) $system['typography']['line_height'];
			$result = wp_update_global_styles( array( 'styles' => $gs ) );
			$applied['global_styles'] = ! is_wp_error( $result );
		}

		// CSS variables (builder-agnostic, works with custom CSS support).
		$css = self::to_css_vars( $system );
		$current = function_exists( 'wp_get_custom_css' ) ? wp_get_custom_css() : '';
		$marker  = '/* AIWC-DESIGN-SYSTEM */';
		$pattern = '/\/\* AIWC-DESIGN-SYSTEM \*\/.*?(?=\/\* AIWC-DESIGN-SYSTEM-END \*\/|$)/s';
		if ( preg_match( $pattern, $current ) ) {
			$css_block = $marker . "\n" . $css . "\n/* AIWC-DESIGN-SYSTEM-END */\n";
			$new = preg_replace( $pattern, $css_block, $current, 1 );
		} else {
			$new = trim( $current . "\n\n" . $marker . "\n" . $css . "\n/* AIWC-DESIGN-SYSTEM-END */\n" );
		}
		$r = wp_update_custom_css_post( $new );
		$applied['css_vars'] = ! is_wp_error( $r );
		return $applied;
	}

	/**
	 * CSS custom properties + responsive helpers generated from tokens.
	 *
	 * @param array|null $system System.
	 * @return string CSS.
	 */
	public static function to_css_vars( $system = null ) {
		$s = $system ? $system : self::get();
		$lines = array( ':root {' );
		foreach ( $s['colors'] as $k => $v ) {
			$lines[] = sprintf( '  --aiwc-color-%s: %s;', $k, $v );
		}
		foreach ( $s['typography'] as $k => $v ) {
			$lines[] = sprintf( '  --aiwc-type-%s: %s;', $k, $v );
		}
		foreach ( $s['radius'] as $k => $v ) {
			$lines[] = sprintf( '  --aiwc-radius-%s: %s;', $k, $v );
		}
		foreach ( $s['shadows'] as $k => $v ) {
			$lines[] = sprintf( '  --aiwc-shadow-%s: %s;', $k, $v );
		}
		foreach ( $s['spacing'] as $k => $v ) {
			$lines[] = sprintf( '  --aiwc-space-%s: %s;', $k, $v );
		}
		foreach ( $s['container'] as $k => $v ) {
			$lines[] = sprintf( '  --aiwc-container-%s: %s;', $k, $v );
		}
		foreach ( $s['buttons'] as $k => $v ) {
			$lines[] = sprintf( '  --aiwc-btn-%s: %s;', $k, '' === $v ? $s['colors']['primary'] : $v );
		}
		$lines[] = '}';
		$lines[] = '.aiwc-container { max-width: var(--aiwc-container-width); margin-inline: auto; padding-inline: var(--aiwc-container-padding); }';
		$lines[] = sprintf( '@media (max-width: %s) { .aiwc-container { padding-inline: var(--aiwc-space-md); } }', $s['breakpoints']['tablet'] );
		$lines[] = sprintf( '@media (max-width: %s) { .aiwc-container { padding-inline: var(--aiwc-space-sm); } }', $s['breakpoints']['mobile'] );
		return implode( "\n", $lines );
	}

	/**
	 * Compact human-readable context for prompts (token budget friendly).
	 *
	 * @param array|null $system System.
	 * @return string
	 */
	public static function to_context( $system = null ) {
		$s = $system ? $system : self::get();
		return sprintf(
			"Design System: primary=%s secondary=%s accent=%s text=%s bg=%s | fonts: body=%s heading=%s | h1=%s h2=%s | radius md=%s | container=%s | buttons radius=%s padding=%s/%s | breakpoints mobile=%s tablet=%s",
			$s['colors']['primary'],
			$s['colors']['secondary'],
			$s['colors']['accent'],
			$s['colors']['text'],
			$s['colors']['bg'],
			$s['typography']['body_font'],
			$s['typography']['heading_font'],
			$s['typography']['h1_size'],
			$s['typography']['h2_size'],
			$s['radius']['md'],
			$s['container']['width'],
			$s['buttons']['radius'],
			$s['buttons']['padding_x'],
			$s['buttons']['padding_y'],
			$s['breakpoints']['mobile'],
			$s['breakpoints']['tablet']
		);
	}
}
