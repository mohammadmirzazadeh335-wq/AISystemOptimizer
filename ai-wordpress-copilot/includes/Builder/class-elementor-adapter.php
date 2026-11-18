<?php
/**
 * Elementor adapter: builds real _elementor_data structures with the storage
 * shape of the INSTALLED Elementor version — container elements for 3.16+
 * (or the container experiment), legacy section/column for older versions.
 *
 * @package AIWC
 */

namespace AIWC\Builder;

defined( 'ABSPATH' ) || exit;

/**
 * Class Elementor_Adapter
 */
class Elementor_Adapter {

	/**
	 * Design tokens.
	 *
	 * @var array
	 */
	private $design;

	/**
	 * Container-based storage?
	 *
	 * @var bool
	 */
	private $containers;

	/**
	 * Constructor.
	 *
	 * @param array $design Design tokens.
	 */
	public function __construct( array $design = array() ) {
		$this->design     = $design ? $design : Design_System::get();
		$this->containers = self::uses_containers();
	}

	/**
	 * Detect whether the installed Elementor stores layouts as containers.
	 *
	 * Priority: explicit filter → version heuristics (3.16+ default-on;
	 * 3.6–3.15 requires the container experiment) → legacy.
	 *
	 * @return bool
	 */
	public static function uses_containers() {
		$filtered = apply_filters( 'aiwc_elementor_uses_containers', null );
		if ( null !== $filtered ) {
			return (bool) $filtered;
		}
		// The option is what Elementor itself persists on activation/upgrade;
		// prefer it over the constant so stored state always wins.
		$version = (string) get_option( 'elementor_version' );
		if ( '' === $version && defined( 'ELEMENTOR_VERSION' ) ) {
			$version = ELEMENTOR_VERSION;
		}
		if ( '' === $version ) {
			return true; // Unknown modern install: prefer containers.
		}
		if ( version_compare( $version, '3.16.0', '>=' ) ) {
			return true;
		}
		if ( version_compare( $version, '3.6.0', '>=' ) ) {
			return 'active' === get_option( 'elementor_experiment-container', 'inactive' );
		}
		return false;
	}

	/**
	 * Is Elementor available?
	 *
	 * @return bool
	 */
	public static function is_available() {
		return defined( 'ELEMENTOR_VERSION' ) || '' !== (string) get_option( 'elementor_version' ) || did_action( 'elementor/loaded' );
	}

	/**
	 * Build one section spec into an elementor element (container or section).
	 *
	 * @param array $spec Section spec.
	 * @return array Elementor element.
	 */
	public function render_section( array $spec ) {
		$style   = isset( $spec['style'] ) ? $spec['style'] : array();
		$layout  = isset( $spec['layout'] ) ? $spec['layout'] : array();
		$columns = max( 1, (int) ( isset( $layout['columns'] ) ? $layout['columns'] : 1 ) );

		$widgets = array();
		foreach ( isset( $spec['elements'] ) ? $spec['elements'] : array() as $el ) {
			foreach ( $this->element_widgets( $el ) as $w ) {
				$widgets[] = $w;
			}
		}

		$bg = isset( $style['bg'] ) ? $this->color( $style['bg'] ) : '';
		$pad = isset( $this->design['spacing'][ isset( $style['padding'] ) ? $style['padding'] : 'lg' ] ) ? $this->design['spacing'][ isset( $style['padding'] ) ? $style['padding'] : 'lg' ] : '48px';

		if ( $this->containers ) {
			// Split widgets across N inner containers (equal width).
			$per    = (int) ceil( count( $widgets ) / $columns );
			$chunks = array_chunk( $widgets, $per ? $per : 1 );
			$inner  = array();
			foreach ( $chunks as $chunk ) {
				$inner[] = $this->wrap_container( $chunk, '', '' );
			}
			return $this->wrap_container( $inner, $bg, $pad, true );
		}

		// Legacy: section → columns → widgets.
		$per    = (int) ceil( count( $widgets ) / $columns );
		$chunks = array_chunk( $widgets, $per ? $per : 1 );
		$cols   = array();
		$size   = floor( 100 / max( 1, count( $chunks ) ) );
		foreach ( $chunks as $chunk ) {
			$cols[] = array(
				'id'       => self::id(),
				'elType'   => 'column',
				'settings' => array( '_column_size' => $size ),
				'elements' => $chunk,
			);
		}
		$settings = array(
			'layout'              => 'boxed',
			'content_width'       => array( 'unit' => 'px', 'size' => (int) $this->design['container']['width'] ),
			'padding'             => array( 'unit' => 'px', 'top' => (int) $pad, 'right' => 24, 'bottom' => (int) $pad, 'left' => 24, 'isLinked' => false ),
		);
		if ( $bg ) {
			$settings['background_background'] = 'classic';
			$settings['background_color']      = $bg;
		}
		return array(
			'id'       => self::id(),
			'elType'   => 'section',
			'settings' => $settings,
			'elements' => $cols,
		);
	}

	/**
	 * Wrap widgets (or nested containers) in a container element.
	 *
	 * @param array  $elements Inner elements.
	 * @param string $bg       Background color.
	 * @param string $pad      Padding px.
	 * @param bool   $row      Flex row (containers only).
	 * @return array
	 */
	private function wrap_container( array $elements, $bg, $pad, $row = false ) {
		$settings = array(
			'layout'        => $row ? 'flex' : 'boxed',
			'flex_direction' => 'row',
			'content_width' => array( 'unit' => 'px', 'size' => (int) $this->design['container']['width'] ),
			'padding'       => array( 'unit' => 'px', 'top' => (int) $pad, 'right' => 24, 'bottom' => (int) $pad, 'left' => 24, 'isLinked' => false ),
		);
		if ( $bg ) {
			$settings['background_background'] = 'classic';
			$settings['background_color']      = $bg;
		}
		return array(
			'id'       => self::id(),
			'elType'   => 'container',
			'settings' => $settings,
			'elements' => $elements,
		);
	}

	/**
	 * Element → widget(s).
	 *
	 * @param array $el Element.
	 * @return array
	 */
	private function element_widgets( array $el ) {
		$kind = isset( $el['kind'] ) ? $el['kind'] : 'text';
		switch ( $kind ) {
			case 'heading':
				$level = max( 1, min( 6, (int) ( isset( $el['level'] ) ? $el['level'] : 2 ) ) );
				return array(
					array(
						'id'         => self::id(),
						'elType'     => 'widget',
						'widgetType' => 'heading',
						'settings'   => array(
							'title'               => (string) ( isset( $el['text'] ) ? $el['text'] : '' ),
							'header_size'         => 'h' . $level,
							'align'               => 'center',
							'title_color'         => $this->design['colors']['text'],
							'typography_typography' => 'custom',
							'typography_font_size'  => array( 'unit' => 'px', 'size' => $this->heading_px( $level ) ),
						),
					),
				);

			case 'text':
				return array(
					array(
						'id'         => self::id(),
						'elType'     => 'widget',
						'widgetType' => 'text-editor',
						'settings'   => array(
							'editor'           => '<p>' . esc_html( (string) ( isset( $el['text'] ) ? $el['text'] : '' ) ) . '</p>',
							'text_color'       => $this->design['colors']['text'],
							'typography_typography' => 'custom',
							'typography_font_size'  => array( 'unit' => 'px', 'size' => (int) $this->design['typography']['base_size'] ),
						),
					),
				);

			case 'button':
				return array(
					array(
						'id'         => self::id(),
						'elType'     => 'widget',
						'widgetType' => 'button',
						'settings'   => array(
							'text'              => (string) ( isset( $el['text'] ) ? $el['text'] : '' ),
							'link'              => array( 'url' => (string) ( isset( $el['url'] ) ? $el['url'] : '#' ), 'is_external' => '', 'nofollow' => '' ),
							'button_text_color' => '#ffffff',
							'background_color'  => $this->design['buttons']['primary_bg'] ? $this->design['buttons']['primary_bg'] : $this->design['colors']['primary'],
							'border_radius'     => array( 'unit' => 'px', 'top' => (int) $this->design['buttons']['radius'], 'right' => (int) $this->design['buttons']['radius'], 'bottom' => (int) $this->design['buttons']['radius'], 'left' => (int) $this->design['buttons']['radius'], 'isLinked' => true ),
							'button_padding'    => array( 'unit' => 'px', 'top' => (int) $this->design['buttons']['padding_y'], 'right' => (int) $this->design['buttons']['padding_x'], 'bottom' => (int) $this->design['buttons']['padding_y'], 'left' => (int) $this->design['buttons']['padding_x'], 'isLinked' => false ),
						),
					),
				);

			case 'image':
				if ( empty( $el['url'] ) ) {
					return array();
				}
				return array(
					array(
						'id'         => self::id(),
						'elType'     => 'widget',
						'widgetType' => 'image',
						'settings'   => array(
							'image' => array(
								'url' => (string) $el['url'],
								'id'  => isset( $el['id'] ) ? (int) $el['id'] : '',
								'alt' => (string) ( isset( $el['alt'] ) ? $el['alt'] : '' ),
								'size' => '',
							),
							'image_border_radius' => array( 'unit' => 'px', 'top' => (int) $this->design['radius']['md'], 'right' => (int) $this->design['radius']['md'], 'bottom' => (int) $this->design['radius']['md'], 'left' => (int) $this->design['radius']['md'], 'isLinked' => true ),
						),
					),
				);

			case 'divider':
				return array(
					array(
						'id'         => self::id(),
						'elType'     => 'widget',
						'widgetType' => 'divider',
						'settings'   => array(),
					),
				);

			case 'card':
			case 'stat':
			case 'quote':
			case 'price_card':
			case 'qa':
				// Flatten composite elements into heading/text widgets (kept real).
				$out = array();
				if ( ! empty( $el['title'] ) || ! empty( $el['q'] ) || ! empty( $el['value'] ) ) {
					$out = array_merge( $out, $this->element_widgets( array( 'kind' => 'heading', 'level' => 3, 'text' => isset( $el['title'] ) ? $el['title'] : ( isset( $el['q'] ) ? $el['q'] : ( isset( $el['value'] ) ? $el['value'] : '' ) ) ) ) );
				}
				if ( ! empty( $el['price'] ) ) {
					$out = array_merge( $out, $this->element_widgets( array( 'kind' => 'heading', 'level' => 2, 'text' => $el['price'] ) ) );
				}
				$body = isset( $el['text'] ) ? $el['text'] : ( isset( $el['a'] ) ? $el['a'] : ( isset( $el['label'] ) ? $el['label'] : '' ) );
				if ( '' !== (string) $body ) {
					$out = array_merge( $out, $this->element_widgets( array( 'kind' => 'text', 'text' => $body ) ) );
				}
				if ( ! empty( $el['features'] ) && is_array( $el['features'] ) ) {
					$li = '';
					foreach ( $el['features'] as $f ) {
						$li .= '<li>' . esc_html( (string) $f ) . '</li>';
					}
					$out[] = array(
						'id'         => self::id(),
						'elType'     => 'widget',
						'widgetType' => 'text-editor',
						'settings'   => array( 'editor' => '<ul>' . $li . '</ul>' ),
					);
				}
				if ( ! empty( $el['button'] ) ) {
					$out = array_merge( $out, $this->element_widgets( array( 'kind' => 'button', 'text' => $el['button'], 'url' => '#contact' ) ) );
				}
				if ( ! empty( $el['author'] ) ) {
					$out = array_merge( $out, $this->element_widgets( array( 'kind' => 'text', 'text' => '— ' . $el['author'] ) ) );
				}
				return $out;

			case 'html':
				$html = (string) ( isset( $el['html'] ) ? $el['html'] : '' );
				if ( '' === trim( $html ) ) {
					return array();
				}
				return array(
					array(
						'id'         => self::id(),
						'elType'     => 'widget',
						'widgetType' => 'html',
						'settings'   => array( 'html' => $html ),
					),
				);

			case 'navigation':
			case 'nav_links':
			case 'link_group':
				$items = array();
				if ( ! empty( $el['links'] ) ) {
					foreach ( $el['links'] as $link ) {
						$text = is_array( $link ) ? (string) ( isset( $link['text'] ) ? $link['text'] : '' ) : (string) $link;
						$items[] = '<li><a href="#">' . esc_html( $text ) . '</a></li>';
					}
				}
				if ( ! empty( $el['title'] ) ) {
					$out = $this->element_widgets( array( 'kind' => 'heading', 'level' => 4, 'text' => $el['title'] ) );
				} else {
					$out = array();
				}
				if ( $items ) {
					$out[] = array(
						'id'         => self::id(),
						'elType'     => 'widget',
						'widgetType' => 'text-editor',
						'settings'   => array( 'editor' => '<ul>' . implode( '', $items ) . '</ul>' ),
					);
				}
				return $out;

			default:
				return $this->element_widgets( array( 'kind' => 'text', 'text' => isset( $el['text'] ) ? $el['text'] : '' ) );
		}
	}

	/**
	 * Heading level → px size from design tokens.
	 *
	 * @param int $level Level.
	 * @return int
	 */
	private function heading_px( $level ) {
		$map = array(
			1 => $this->design['typography']['h1_size'],
			2 => $this->design['typography']['h2_size'],
			3 => $this->design['typography']['h3_size'],
			4 => $this->design['typography']['h4_size'],
		);
		$size = isset( $map[ $level ] ) ? $map[ $level ] : $this->design['typography']['h4_size'];
		if ( preg_match( '/(\d+(?:\.\d+)?)(px|rem|em)/', (string) $size, $m ) ) {
			$val = (float) $m[1];
			if ( 'rem' === $m[2] || 'em' === $m[2] ) {
				$val *= 16;
			}
			return (int) round( $val );
		}
		return 24;
	}

	/**
	 * Resolve token color.
	 *
	 * @param string $name Name/literal.
	 * @return string
	 */
	private function color( $name ) {
		return isset( $this->design['colors'][ $name ] ) ? $this->design['colors'][ $name ] : (string) $name;
	}

	/**
	 * Random element id like Elementor (7 hex chars).
	 *
	 * @return string
	 */
	public static function id() {
		return substr( md5( uniqid( (string) wp_rand(), true ) ), 0, 7 );
	}

	/**
	 * Create a full Elementor page from section specs.
	 *
	 * @param string $title Title.
	 * @param array  $specs Section specs.
	 * @param array  $args  post_status, slug.
	 * @return int|\WP_Error Post ID.
	 */
	public function create_page( $title, array $specs, array $args = array() ) {
		$data = array();
		foreach ( $specs as $spec ) {
			if ( is_array( $spec ) ) {
				$data[] = $this->render_section( $spec );
			}
		}
		$valid = self::validate_data( $data );
		if ( is_wp_error( $valid ) ) {
			return $valid;
		}
		$post_id = wp_insert_post(
			array(
				'post_title'   => (string) $title,
				'post_content' => '',
				'post_status'  => isset( $args['post_status'] ) ? (string) $args['post_status'] : 'publish',
				'post_type'    => isset( $args['post_type'] ) ? (string) $args['post_type'] : 'page',
				'post_name'    => ! empty( $args['slug'] ) ? sanitize_title( (string) $args['slug'] ) : '',
			),
			true
		);
		if ( is_wp_error( $post_id ) ) {
			return $post_id;
		}
		self::save_data( (int) $post_id, $data );
		return (int) $post_id;
	}

	/**
	 * Save _elementor_data and bookkeeping meta.
	 *
	 * @param int   $post_id Post ID.
	 * @param array $data    Elementor data.
	 * @return bool
	 */
	public static function save_data( $post_id, array $data ) {
		update_post_meta( $post_id, '_elementor_edit_mode', 'builder' );
		update_post_meta( $post_id, '_elementor_template_type', 'wp-page' );
		update_post_meta( $post_id, '_elementor_version', defined( 'ELEMENTOR_VERSION' ) ? ELEMENTOR_VERSION : (string) get_option( 'elementor_version' ) );
		return (bool) update_post_meta( $post_id, '_elementor_data', wp_slash( wp_json_encode( $data ) ) );
	}

	/**
	 * Validate elementor data structure (recursively).
	 *
	 * @param array $data Elements.
	 * @return true|\WP_Error
	 */
	public static function validate_data( array $data ) {
		static $depth = 0;
		if ( $depth > 8 ) {
			return new \WP_Error( 'aiwc_elementor_depth', 'Elementor structure too deep.' );
		}
		foreach ( $data as $el ) {
			if ( ! is_array( $el ) || empty( $el['elType'] ) || empty( $el['id'] ) ) {
				return new \WP_Error( 'aiwc_elementor_shape', 'Malformed elementor element (id/elType required).' );
			}
			if ( ! in_array( $el['elType'], array( 'section', 'column', 'container', 'widget' ), true ) ) {
				return new \WP_Error( 'aiwc_elementor_shape', 'Unknown elType: ' . $el['elType'] );
			}
			if ( 'widget' === $el['elType'] && empty( $el['widgetType'] ) ) {
				return new \WP_Error( 'aiwc_elementor_shape', 'Widget without widgetType.' );
			}
			if ( isset( $el['elements'] ) && is_array( $el['elements'] ) ) {
				++$depth;
				$r = self::validate_data( $el['elements'] );
				--$depth;
				if ( is_wp_error( $r ) ) {
					return $r;
				}
			}
		}
		return true;
	}
}
