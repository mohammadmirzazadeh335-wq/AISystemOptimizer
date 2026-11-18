<?php
/**
 * Design Engine: orchestrates the design system, section library and the
 * builder adapters (Elementor / Gutenberg) into real, visible pages.
 *
 * Builder priority: admin override (preferred_builder) → Elementor →
 * Gutenberg (block theme) → Gutenberg on classic themes.
 *
 * @package AIWC
 */

namespace AIWC\Builder;

defined( 'ABSPATH' ) || exit;

/**
 * Class Design_Engine
 */
class Design_Engine {

	/**
	 * Resolve the builder to use.
	 *
	 * @param string $requested auto|elementor|gutenberg|classic.
	 * @return string gutenberg|elementor.
	 */
	public static function resolve_builder( $requested = 'auto' ) {
		$requested = (string) $requested;
		if ( 'auto' === $requested || '' === $requested ) {
			$requested = (string) \AIWC\Settings::get( 'preferred_builder' );
		}
		if ( 'elementor' === $requested && Elementor_Adapter::is_available() ) {
			return 'elementor';
		}
		if ( 'gutenberg' === $requested || 'classic' === $requested ) {
			return 'gutenberg';
		}
		// Auto priority: Elementor > Gutenberg.
		if ( Elementor_Adapter::is_available() ) {
			return 'elementor';
		}
		return 'gutenberg';
	}

	/**
	 * Build a real page from section specs.
	 *
	 * @param string $title    Page title.
	 * @param array  $sections Each: {type, content?} or a raw spec array.
	 * @param array  $args     slug, post_status, builder.
		* @return array|\WP_Error {post_id, url, builder, sections}.
	 */
	public static function build_page( $title, array $sections, array $args = array() ) {
		$design  = Design_System::get();
		$builder = self::resolve_builder( isset( $args['builder'] ) ? $args['builder'] : 'auto' );

		$specs = array();
		foreach ( $sections as $s ) {
			if ( ! is_array( $s ) ) {
				continue;
			}
			if ( isset( $s['elements'] ) && isset( $s['type'] ) ) {
				$specs[] = $s; // Already a raw spec.
				continue;
			}
			$type    = isset( $s['type'] ) ? (string) $s['type'] : '';
			$content = isset( $s['content'] ) && is_array( $s['content'] ) ? $s['content'] : array();
			$spec    = Section_Library::section( $type, $content, $design );
			if ( null === $spec ) {
				return new \WP_Error( 'aiwc_unknown_section', sprintf( 'Unknown section type: %s', $type ) );
			}
			$specs[] = $spec;
		}
		if ( ! $specs ) {
			return new \WP_Error( 'aiwc_no_sections', 'No sections provided.' );
		}

		if ( 'elementor' === $builder ) {
			$adapter = new Elementor_Adapter( $design );
			$post_id = $adapter->create_page( $title, $specs, $args );
		} else {
			$adapter = new Gutenberg_Adapter( $design );
			$post_id = $adapter->create_page( $title, $specs, $args );
		}
		if ( is_wp_error( $post_id ) ) {
			return $post_id;
		}

		// Apply design system tokens to the environment so the page matches.
		Design_System::apply( $design );

		return array(
			'post_id'  => (int) $post_id,
			'url'      => get_permalink( (int) $post_id ),
			'builder'  => $builder,
			'sections' => array_map(
				function ( $s ) {
					return isset( $s['type'] ) ? $s['type'] : 'custom';
				},
				$specs
			),
		);
	}

	/**
	 * Environment status for prompts and UI.
	 *
	 * @return array
	 */
	public static function status() {
		$detection = Design_System::detect();
		return array(
			'builder_resolved'   => self::resolve_builder( 'auto' ),
			'elementor'          => Elementor_Adapter::is_available() ? 'available' : 'not_installed',
			'elementor_storage'  => Elementor_Adapter::uses_containers() ? 'containers' : 'section_column',
			'gutenberg'          => wp_is_block_theme() ? 'block_theme' : 'classic_theme',
			'preferred_builder'  => (string) \AIWC\Settings::get( 'preferred_builder' ),
			'design_source'      => $detection['source'],
			'design'             => $detection['tokens'],
		);
	}
}
