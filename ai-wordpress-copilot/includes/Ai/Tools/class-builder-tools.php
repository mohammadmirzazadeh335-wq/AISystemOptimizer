<?php
/**
 * Website Builder tools: design system, section library, page building and
 * structural block edits — all producing real WordPress output.
 *
 * @package AIWC
 */

namespace AIWC\Ai\Tools;

use AIWC\Ai\Abstract_Tool_Group;
use AIWC\Builder\Design_Engine;
use AIWC\Builder\Design_System;
use AIWC\Builder\Elementor_Adapter;
use AIWC\Builder\Gutenberg_Adapter;
use AIWC\Builder\Redesign_Engine;
use AIWC\Builder\Section_Library;

defined( 'ABSPATH' ) || exit;

/**
 * Class Builder_Tools
 */
class Builder_Tools extends Abstract_Tool_Group {

	/**
	 * Group id.
	 *
	 * @var string
	 */
	protected $group = 'builder';

	/**
	 * Tool schemas.
	 *
	 * @return array[]
	 */
	public function tools() {
		return array(
			array(
				'name'        => 'get_design_system',
				'handler'     => 'handle_get_design_system',
				'description' => 'Get the central design system (colors, fonts, sizes, radius, shadows, spacing, container, buttons, breakpoints) and where it was detected from (elementor > gutenberg > theme).',
				'parameters'  => array( 'type' => 'object', 'properties' => new \stdClass(), 'required' => array() ),
			),
			array(
				'name'        => 'update_design_system',
				'handler'     => 'handle_update_design_system',
				'description' => 'Update design system tokens. Only pass the values that change (e.g. {"colors":{"primary":"#1e3a5f"}}). Applied globally: Global Styles + CSS variables. Map natural-language requests («رنگ اصلی را سرمه‌ای کن») to concrete tokens here.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'colors'      => array( 'type' => 'object', 'description' => 'primary, secondary, accent, text, muted, bg, surface (hex colors).' ),
						'typography'  => array( 'type' => 'object', 'description' => 'body_font, heading_font, base_size, h1_size, h2_size, h3_size, h4_size, weight_body, weight_heading, line_height.' ),
						'radius'      => array( 'type' => 'object', 'description' => 'sm, md, lg (CSS sizes).' ),
						'shadows'     => array( 'type' => 'object', 'description' => 'sm, md, lg (CSS box-shadow).' ),
						'spacing'     => array( 'type' => 'object', 'description' => 'xs, sm, md, lg, xl (CSS sizes).' ),
						'container'   => array( 'type' => 'object', 'description' => 'width, padding.' ),
						'buttons'     => array( 'type' => 'object', 'description' => 'radius, padding_x, padding_y, weight, primary_bg.' ),
						'breakpoints' => array( 'type' => 'object', 'description' => 'mobile, tablet (CSS sizes).' ),
					),
					'required'   => array(),
				),
			),
			array(
				'name'        => 'list_sections',
				'handler'     => 'handle_list_sections',
				'description' => 'List available section templates (hero, features, pricing, faq, ...) and saved reusable components.',
				'parameters'  => array( 'type' => 'object', 'properties' => new \stdClass(), 'required' => array() ),
			),
			array(
				'name'        => 'build_page',
				'handler'     => 'handle_build_page',
				'description' => 'Build a complete page from section templates. Sections = [{type, content}] where content overrides texts/images/links. Produces real blocks (Gutenberg) or real Elementor data matching the installed version.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'title'    => array( 'type' => 'string', 'description' => 'Page title.' ),
						'slug'     => array( 'type' => 'string', 'description' => 'Optional URL slug.' ),
						'status'   => array( 'type' => 'string', 'description' => 'publish or draft (default publish).' ),
						'builder'  => array( 'type' => 'string', 'description' => 'auto (default), gutenberg or elementor.' ),
						'sections' => array(
							'type'        => 'array',
							'description' => 'Ordered sections.',
							'items'       => array(
								'type'       => 'object',
								'properties' => array(
									'type'    => array( 'type' => 'string', 'description' => 'Section type from list_sections.' ),
									'content' => array( 'type' => 'object', 'description' => 'Content overrides (heading, text, items, images, links...).' ),
								),
								'required'   => array( 'type' ),
							),
						),
					),
					'required'   => array( 'title', 'sections' ),
				),
			),
			array(
				'name'        => 'get_page_structure',
				'handler'     => 'handle_get_page_structure',
				'description' => 'List the top-level blocks/elements of a page with indexes (for edit_page_structure).',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array( 'post_id' => array( 'type' => 'integer' ) ),
					'required'   => array( 'post_id' ),
				),
			),
			array(
				'name'        => 'edit_page_structure',
				'handler'     => 'handle_edit_page_structure',
				'description' => 'Structural edits on a Gutenberg page: delete_block, move_block, update_block, wrap_in_group, add_columns. Indexes refer to top-level blocks from get_page_structure.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'post_id' => array( 'type' => 'integer' ),
						'op'      => array( 'type' => 'string', 'description' => 'delete_block | move_block | update_block | wrap_in_group | add_columns' ),
						'index'   => array( 'type' => 'integer', 'description' => 'Block index (or "from" for move).' ),
						'to'      => array( 'type' => 'integer', 'description' => 'Target index (move_block).' ),
						'indexes' => array( 'type' => 'array', 'description' => 'Indexes for wrap_in_group.' ),
						'attrs'   => array( 'type' => 'object', 'description' => 'Attributes for update_block.' ),
						'content' => array( 'type' => 'string', 'description' => 'Text content for update_block.' ),
						'columns' => array( 'type' => 'array', 'description' => 'Column contents for add_columns (each a list of texts).' ),
					),
					'required'   => array( 'post_id', 'op' ),
				),
			),
			array(
				'name'        => 'manage_component',
				'handler'     => 'handle_manage_component',
				'description' => 'Save, list or delete reusable section components (named specs re-usable across pages).',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'action'    => array( 'type' => 'string', 'description' => 'save | list | delete' ),
						'name'      => array( 'type' => 'string', 'description' => 'Component name (save/delete).' ),
						'type'      => array( 'type' => 'string', 'description' => 'Section type to save as component.' ),
						'content'   => array( 'type' => 'object', 'description' => 'Content overrides when saving.' ),
					),
					'required'   => array( 'action' ),
				),
			),
			array(
				'name'        => 'redesign_page',
				'description' => 'Redesign a page safely: action=analyze (content inventory + design critique + proposal), action=preview (build a draft preview copy; the original stays untouched), action=apply (replace the page with the preview — REQUIRES confirm=true and user approval; content is snapshot-protected), action=compare (before/after structural comparison; screenshots unavailable in this environment).',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'post_id'    => array( 'type' => 'integer', 'description' => 'Page to redesign.' ),
						'action'     => array( 'type' => 'string', 'description' => 'analyze | preview | apply | compare' ),
						'proposal'   => array( 'type' => 'object', 'description' => 'Optional adjusted proposal for preview (sections/preserved/removed).' ),
						'preview_id' => array( 'type' => 'integer', 'description' => 'Preview post ID (required for apply).' ),
						'confirm'    => array( 'type' => 'boolean', 'description' => 'Explicit user-confirmed approval (required for apply).' ),
					),
					'required'   => array( 'post_id', 'action' ),
				),
				'handler'     => 'handle_redesign_page',
				'risk'        => 'write',
			),
			array(
				'name'        => 'get_builder_status',
				'handler'     => 'handle_get_builder_status',
				'description' => 'Builder environment: resolved builder (auto priority Elementor > Gutenberg), Elementor storage format, theme type, design detection source.',
				'parameters'  => array( 'type' => 'object', 'properties' => new \stdClass(), 'required' => array() ),
			),
		);
	}

	/**
	 * get_design_system
	 *
	 * @return array
	 */
	public function handle_get_design_system() {
		$detection = Design_System::detect();
		return $this->success(
			array(
				'design'       => Design_System::get(),
				'css_vars'     => Design_System::to_css_vars(),
				'detected_from' => $detection['source'],
				'detected'     => $detection['tokens'],
			),
			'Design system loaded.'
		);
	}

	/**
	 * update_design_system
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_update_design_system( array $args ) {
		$patch = array();
		foreach ( array( 'colors', 'typography', 'radius', 'shadows', 'spacing', 'container', 'buttons', 'breakpoints' ) as $group ) {
			if ( isset( $args[ $group ] ) && is_array( $args[ $group ] ) ) {
				$patch[ $group ] = $args[ $group ];
			}
		}
		if ( ! $patch ) {
			return $this->error( 'No design tokens provided.' );
		}
		$saved   = Design_System::update( $patch );
		$applied = Design_System::apply( $saved );
		return $this->success(
			array(
				'design'  => $saved,
				'applied' => $applied,
			),
			'Design system updated and applied.'
		);
	}

	/**
	 * list_sections
	 *
	 * @return array
	 */
	public function handle_list_sections() {
		return $this->success(
			array(
				'sections'    => Section_Library::types(),
				'components' => array_keys( Section_Library::list_components() ),
			),
			'Section library loaded.'
		);
	}

	/**
	 * build_page
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_build_page( array $args ) {
		$title = isset( $args['title'] ) ? trim( (string) $args['title'] ) : '';
		if ( '' === $title ) {
			return $this->error( 'Page title is required.' );
		}
		$sections = isset( $args['sections'] ) && is_array( $args['sections'] ) ? $args['sections'] : array();
		$build    = array(
			'slug'        => isset( $args['slug'] ) ? (string) $args['slug'] : '',
			'post_status' => isset( $args['status'] ) ? (string) $args['status'] : 'publish',
			'builder'     => isset( $args['builder'] ) ? (string) $args['builder'] : 'auto',
		);
		$result = Design_Engine::build_page( $title, $sections, $build );
		if ( is_wp_error( $result ) ) {
			return $this->error( $result->get_error_message() );
		}
		return $this->success( $result, 'Page built: ' . $result['url'] );
	}

	/**
	 * get_page_structure
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_get_page_structure( array $args ) {
		$post_id = isset( $args['post_id'] ) ? (int) $args['post_id'] : 0;
		$post    = get_post( $post_id );
		if ( ! $post ) {
			return $this->error( 'Post not found.' );
		}

		$elementor = get_post_meta( $post_id, '_elementor_data', true );
		if ( $elementor ) {
			$data  = json_decode( (string) $elementor, true );
			$items = array();
			foreach ( is_array( $data ) ? $data : array() as $i => $el ) {
				$items[] = array(
					'index'   => $i,
					'type'    => isset( $el['elType'] ) ? $el['elType'] : '?',
					'widget'  => isset( $el['widgetType'] ) ? $el['widgetType'] : '',
					'preview' => self::element_preview( $el ),
				);
			}
			return $this->success(
				array( 'builder' => 'elementor', 'blocks' => $items ),
				'Elementor structure loaded.'
			);
		}

		$adapter = new Gutenberg_Adapter();
		$blocks  = $adapter->get_blocks( $post_id );
		if ( is_wp_error( $blocks ) ) {
			return $this->error( $blocks->get_error_message() );
		}
		$items = array();
		foreach ( $blocks as $i => $b ) {
			$items[] = array(
				'index'   => $i,
				'type'    => $b['blockName'],
				'preview' => mb_substr( wp_strip_all_tags( isset( $b['innerHTML'] ) ? $b['innerHTML'] : '' ), 0, 80 ),
			);
		}
		return $this->success(
			array( 'builder' => 'gutenberg', 'blocks' => $items ),
			'Page structure loaded.'
		);
	}

	/**
	 * edit_page_structure (Gutenberg only — Elementor pages expose structure
	 * read-only; regenerate with build_page for elementor edits).
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_edit_page_structure( array $args ) {
		$post_id = isset( $args['post_id'] ) ? (int) $args['post_id'] : 0;
		$op      = isset( $args['op'] ) ? (string) $args['op'] : '';
		if ( get_post_meta( $post_id, '_elementor_data', true ) ) {
			return $this->error( 'Elementor pages are edited by rebuilding the page (build_page) or via the Elementor tools.' );
		}
		$adapter = new Gutenberg_Adapter();
		switch ( $op ) {
			case 'delete_block':
				$r = $adapter->delete_block( $post_id, isset( $args['index'] ) ? (int) $args['index'] : -1 );
				break;
			case 'move_block':
				$r = $adapter->move_block( $post_id, isset( $args['index'] ) ? (int) $args['index'] : -1, isset( $args['to'] ) ? (int) $args['to'] : -1 );
				break;
			case 'update_block':
				$r = $adapter->update_block(
					$post_id,
					isset( $args['index'] ) ? (int) $args['index'] : -1,
					isset( $args['attrs'] ) && is_array( $args['attrs'] ) ? $args['attrs'] : array(),
					isset( $args['content'] ) ? (string) $args['content'] : null
				);
				break;
			case 'wrap_in_group':
				$r = $adapter->wrap_in_group( $post_id, isset( $args['indexes'] ) && is_array( $args['indexes'] ) ? $args['indexes'] : array() );
				break;
			case 'add_columns':
				$r = $adapter->add_columns( $post_id, isset( $args['index'] ) ? (int) $args['index'] : 0, isset( $args['columns'] ) && is_array( $args['columns'] ) ? $args['columns'] : array() );
				break;
			default:
				return $this->error( 'Unknown operation: ' . $op );
		}
		if ( is_wp_error( $r ) ) {
			return $this->error( $r->get_error_message() );
		}
		return $this->success( array( 'post_id' => $post_id, 'op' => $op ), 'Structure updated: ' . $op );
	}

	/**
	 * manage_component
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_manage_component( array $args ) {
		$action = isset( $args['action'] ) ? (string) $args['action'] : '';
		if ( 'list' === $action ) {
			$list = array();
			foreach ( Section_Library::list_components() as $name => $c ) {
				$list[] = array( 'name' => $name, 'type' => isset( $c['spec']['type'] ) ? $c['spec']['type'] : '', 'updated_at' => $c['updated_at'] );
			}
			return $this->success( array( 'components' => $list ), 'Components loaded.' );
		}
		if ( 'save' === $action ) {
			$name = isset( $args['name'] ) ? (string) $args['name'] : '';
			$type = isset( $args['type'] ) ? (string) $args['type'] : '';
			$spec = Section_Library::section( $type, isset( $args['content'] ) && is_array( $args['content'] ) ? $args['content'] : array() );
			if ( ! $spec ) {
				return $this->error( 'Unknown section type: ' . $type );
			}
			$ok = Section_Library::save_component( $name, $spec );
			return $ok ? $this->success( array( 'name' => $name ), 'Component saved.' ) : $this->error( 'Invalid component name.' );
		}
		if ( 'delete' === $action ) {
			$ok = Section_Library::delete_component( isset( $args['name'] ) ? (string) $args['name'] : '' );
			return $ok ? $this->success( array(), 'Component deleted.' ) : $this->error( 'Component not found.' );
		}
		return $this->error( 'Unknown action: ' . $action );
	}

	/**
	 * redesign_page
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_redesign_page( array $args ) {
		$post_id = isset( $args['post_id'] ) ? (int) $args['post_id'] : 0;
		$action  = isset( $args['action'] ) ? (string) $args['action'] : '';
		switch ( $action ) {
			case 'analyze':
				$result = Redesign_Engine::analyze( $post_id );
				break;
			case 'preview':
				$proposal = isset( $args['proposal'] ) && is_array( $args['proposal'] ) ? $args['proposal'] : array();
				$result   = Redesign_Engine::preview( $post_id, $proposal );
				break;
			case 'apply':
				$preview_id = isset( $args['preview_id'] ) ? (int) $args['preview_id'] : 0;
				$confirm    = ! empty( $args['confirm'] );
				$result     = Redesign_Engine::apply( $post_id, $preview_id, $confirm );
				break;
			case 'compare':
				$result = Redesign_Engine::compare( $post_id );
				break;
			default:
				return $this->error( 'Unknown redesign action: ' . $action );
		}
		if ( is_wp_error( $result ) ) {
			return $this->error( $result->get_error_message() );
		}
		return $this->success( $result, 'Redesign ' . $action . ' completed.' );
	}

	/**
	 * get_builder_status
	 *
	 * @return array
	 */
	public function handle_get_builder_status() {
		return $this->success( Design_Engine::status(), 'Builder status loaded.' );
	}

	/**
	 * Short preview of an elementor element (looks into nested widgets).
	 *
	 * @param array $el Element.
	 * @return string
	 */
	private static function element_preview( array $el ) {
		if ( ! empty( $el['settings']['title'] ) ) {
			return mb_substr( (string) $el['settings']['title'], 0, 80 );
		}
		if ( ! empty( $el['settings']['editor'] ) ) {
			return mb_substr( wp_strip_all_tags( (string) $el['settings']['editor'] ), 0, 80 );
		}
		if ( ! empty( $el['settings']['text'] ) ) {
			return mb_substr( (string) $el['settings']['text'], 0, 80 );
		}
		if ( ! empty( $el['elements'] ) && is_array( $el['elements'] ) ) {
			$parts = array();
			foreach ( $el['elements'] as $child ) {
				$p = self::element_preview( $child );
				if ( '' !== $p ) {
					$parts[] = $p;
				}
				if ( count( $parts ) >= 3 ) {
					break;
				}
			}
			return implode( ' | ', $parts );
		}
		return '';
	}
}
