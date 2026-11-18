<?php
/**
 * Gutenberg adapter: materializes section specs into real core blocks and
 * performs structural edits (create/edit/delete/move, groups, columns, full
 * pages, Global Styles via Design_System) with valid block markup output.
 *
 * @package AIWC
 */

namespace AIWC\Builder;

defined( 'ABSPATH' ) || exit;

/**
 * Class Gutenberg_Adapter
 */
class Gutenberg_Adapter {

	/**
	 * Design tokens.
	 *
	 * @var array
	 */
	private $design;

	/**
	 * Constructor.
	 *
	 * @param array $design Design system tokens.
	 */
	public function __construct( array $design = array() ) {
		$this->design = $design ? $design : Design_System::get();
	}

	/*
	|--------------------------------------------------------------------------
	| Spec → blocks
	|--------------------------------------------------------------------------
	*/

	/**
	 * Materialize one section spec into serialized block markup.
	 *
	 * @param array $spec Section spec.
	 * @return string Block markup.
	 */
	public function render_section( array $spec ) {
		$blocks = $this->section_blocks( $spec );
		return $this->serialize( $blocks );
	}

	/**
	 * Materialize a list of sections into one block document.
	 *
	 * @param array $specs Section specs.
	 * @return string Block markup.
	 */
	public function render_sections( array $specs ) {
		$blocks = array();
		foreach ( $specs as $spec ) {
			if ( is_array( $spec ) ) {
				$blocks = array_merge( $blocks, $this->section_blocks( $spec ) );
			}
		}
		return $this->serialize( $blocks );
	}

	/**
	 * Serialize block arrays to markup.
	 *
	 * @param array $blocks Block arrays.
	 * @return string
	 */
	private function serialize( array $blocks ) {
		$out = '';
		foreach ( $blocks as $block ) {
			$out .= serialize_block( $this->to_block_array( $block ) );
		}
		return $out;
	}

	/**
	 * Convert compact block form to the parse_blocks array shape.
	 *
	 * Compact form: name, attrs, html (innerHTML for leaves), inner (children).
	 *
	 * @param array $b Compact block.
	 * @return array
	 */
	private function to_block_array( array $b ) {
		$inner = isset( $b['inner'] ) ? $b['inner'] : array();
		$block = array(
			'blockName'    => $b['name'],
			'attrs'        => isset( $b['attrs'] ) ? $b['attrs'] : array(),
			'innerBlocks'  => array_map( array( $this, 'to_block_array' ), $inner ),
			'innerContent' => array_map(
				function ( $child ) {
					return null;
				},
				$inner
			),
			'innerHTML'    => '',
		);
		if ( $inner ) {
			// Parent blocks: serialize_block injects children at null slots.
			return $block;
		}
		$html = isset( $b['html'] ) ? (string) $b['html'] : '';
		$block['innerHTML']    = $html;
		$block['innerContent'] = array( $html );
		return $block;
	}

	/**
	 * Section spec → compact blocks.
	 *
	 * @param array $spec Spec.
	 * @return array
	 */
	private function section_blocks( array $spec ) {
		$style = isset( $spec['style'] ) ? $spec['style'] : array();
		$layout = isset( $spec['layout'] ) ? $spec['layout'] : array();
		$inner  = array();

		$columns = max( 1, (int) ( isset( $layout['columns'] ) ? $layout['columns'] : 1 ) );
		$items   = array();
		foreach ( isset( $spec['elements'] ) ? $spec['elements'] : array() as $el ) {
			$items[] = $this->element_blocks( $el );
		}

		if ( 1 === $columns || count( $items ) < 2 ) {
			foreach ( $items as $group ) {
				foreach ( $group as $blk ) {
					$inner[] = $blk;
				}
			}
		} else {
			// Distribute elements across core/columns (auto-stacking on mobile).
			$per = (int) ceil( count( $items ) / $columns );
			$chunks = array_chunk( $items, $per );
			$columns_inner = array();
			foreach ( $chunks as $chunk ) {
				$col_blocks = array();
				foreach ( $chunk as $group ) {
					foreach ( $group as $blk ) {
						$col_blocks[] = $blk;
					}
				}
				$columns_inner[] = array(
					'name' => 'core/column',
					'attrs' => array( 'width' => floor( 100 / count( $chunks ) ) . '%' ),
					'inner' => $col_blocks,
				);
			}
			$inner[] = array(
				'name' => 'core/columns',
				'attrs' => array(
					'style' => array( 'spacing' => array( 'blockGap' => '24px' ) ),
				),
				'inner' => $columns_inner,
			);
		}

		$group_attrs = array(
			'layout' => array( 'type' => 'constrained', 'contentSize' => $this->design['container']['width'] ),
		);
		if ( isset( $style['bg'] ) && '' !== $style['bg'] ) {
			$group_attrs['style']['color']['background'] = $this->color( $style['bg'] );
		}
		if ( isset( $style['text_color'] ) ) {
			$group_attrs['style']['color']['text'] = $this->color( $style['text_color'] );
		}
		$pad = isset( $this->design['spacing'][ isset( $style['padding'] ) ? $style['padding'] : 'lg' ] ) ? $this->design['spacing'][ isset( $style['padding'] ) ? $style['padding'] : 'lg' ] : '48px';
		$group_attrs['style']['spacing']['padding'] = array(
			'top'    => $pad,
			'bottom' => $pad,
		);

		return array(
			array(
				'name'  => 'core/group',
				'attrs' => $group_attrs,
				'inner' => $inner,
			),
		);
	}

	/**
	 * Resolve a token color name or pass through a literal.
	 *
	 * @param string $name Name or literal.
	 * @return string
	 */
	private function color( $name ) {
		$colors = $this->design['colors'];
		if ( isset( $colors[ $name ] ) ) {
			return $colors[ $name ];
		}
		return (string) $name;
	}

	/**
	 * Element → compact blocks (each element may expand to several blocks).
	 *
	 * @param array $el Element.
	 * @return array
	 */
	private function element_blocks( array $el ) {
		$kind = isset( $el['kind'] ) ? $el['kind'] : 'text';
		switch ( $kind ) {
			case 'heading':
				$level = max( 1, min( 6, (int) ( isset( $el['level'] ) ? $el['level'] : 2 ) ) );
				$text  = (string) ( isset( $el['text'] ) ? $el['text'] : '' );
				return array(
					array(
						'name'  => 'core/heading',
						'attrs' => array( 'level' => $level ),
						'html'  => sprintf( '<h%d>%s</h%d>', $level, esc_html( $text ), $level ),
					),
				);

			case 'text':
				$text = (string) ( isset( $el['text'] ) ? $el['text'] : '' );
				return array(
					array(
						'name' => 'core/paragraph',
						'html' => sprintf( '<p>%s</p>', esc_html( $text ) ),
					),
				);

			case 'button':
				$btn_text = (string) ( isset( $el['text'] ) ? $el['text'] : '' );
				$btn_url  = (string) ( isset( $el['url'] ) ? $el['url'] : '#' );
				return array(
					array(
						'name'  => 'core/buttons',
						'attrs' => array( 'layout' => array( 'type' => 'flex', 'justifyContent' => 'left' ) ),
						'inner' => array(
							array(
								'name'  => 'core/button',
								'attrs' => array(
									'text' => $btn_text,
									'url'  => $btn_url,
									'style' => array(
										'color'     => array( 'background' => $this->design['buttons']['primary_bg'] ? $this->design['buttons']['primary_bg'] : $this->design['colors']['primary'], 'text' => '#ffffff' ),
										'border'    => array( 'radius' => $this->design['buttons']['radius'] ),
										'spacing'   => array( 'padding' => array( 'top' => $this->design['buttons']['padding_y'], 'bottom' => $this->design['buttons']['padding_y'], 'left' => $this->design['buttons']['padding_x'], 'right' => $this->design['buttons']['padding_x'] ) ),
									),
								),
								'html'  => sprintf(
									'<div class="wp-block-button"><a class="wp-block-button__link wp-element-button" href="%s">%s</a></div>',
									esc_url( $btn_url ),
									esc_html( $btn_text )
								),
							),
						),
					),
				);

			case 'image':
				if ( empty( $el['url'] ) ) {
					return array();
				}
				return array(
					array(
						'name'  => 'core/image',
						'attrs' => array(
							'url' => (string) $el['url'],
							'alt' => (string) ( isset( $el['alt'] ) ? $el['alt'] : '' ),
						),
					),
				);

			case 'card':
				return array(
					array(
						'name'  => 'core/group',
						'attrs' => array(
							'style' => array(
								'color'    => array( 'background' => $this->design['colors']['surface'] ),
								'border'   => array( 'radius' => $this->design['radius']['md'] ),
								'spacing'  => array( 'padding' => array( 'top' => $this->design['spacing']['md'], 'bottom' => $this->design['spacing']['md'], 'left' => $this->design['spacing']['md'], 'right' => $this->design['spacing']['md'] ) ),
							),
						),
						'inner' => array(
							array( 'name' => 'core/heading', 'attrs' => array( 'level' => 3 ), 'html' => sprintf( '<h3>%s</h3>', esc_html( (string) ( isset( $el['title'] ) ? $el['title'] : '' ) ) ) ),
							array( 'name' => 'core/paragraph', 'html' => sprintf( '<p>%s</p>', esc_html( (string) ( isset( $el['text'] ) ? $el['text'] : '' ) ) ) ),
						),
					),
				);

			case 'stat':
				return array(
					array(
						'name'  => 'core/group',
						'attrs' => array( 'layout' => array( 'type' => 'flex', 'orientation' => 'vertical', 'justifyContent' => 'center' ) ),
						'inner' => array(
							array( 'name' => 'core/heading', 'attrs' => array( 'level' => 2, 'textAlign' => 'center' ), 'html' => sprintf( '<h2 class="has-text-align-center">%s</h2>', esc_html( (string) ( isset( $el['value'] ) ? $el['value'] : '' ) ) ) ),
							array( 'name' => 'core/paragraph', 'attrs' => array( 'textAlign' => 'center' ), 'html' => sprintf( '<p class="has-text-align-center">%s</p>', esc_html( (string) ( isset( $el['label'] ) ? $el['label'] : '' ) ) ) ),
						),
					),
				);

			case 'quote':
				$quote = esc_html( (string) ( isset( $el['text'] ) ? $el['text'] : '' ) );
				$cite  = esc_html( (string) ( isset( $el['author'] ) ? $el['author'] : '' ) );
				return array(
					array(
						'name' => 'core/pullquote',
						'html' => sprintf(
							'<figure class="wp-block-pullquote"><blockquote><p>%s</p></blockquote><figcaption>%s</figcaption></figure>',
							$quote,
							$cite
						),
					),
				);

			case 'price_card':
				$list_items = array();
				foreach ( isset( $el['features'] ) ? $el['features'] : array() as $f ) {
					$list_items[] = array( 'name' => 'core/list-item', 'html' => esc_html( (string) $f ) );
				}
				return array(
					array(
						'name'  => 'core/group',
						'attrs' => array(
							'style' => array(
								'color'   => array( 'background' => ! empty( $el['featured'] ) ? $this->design['colors']['surface'] : $this->design['colors']['bg'] ),
								'border'  => array( 'radius' => $this->design['radius']['lg'], 'color' => $this->design['colors']['primary'], 'width' => ! empty( $el['featured'] ) ? '2px' : '1px' ),
								'spacing' => array( 'padding' => array( 'top' => $this->design['spacing']['lg'], 'bottom' => $this->design['spacing']['lg'], 'left' => $this->design['spacing']['md'], 'right' => $this->design['spacing']['md'] ) ),
							),
						),
						'inner' => array(
							array( 'name' => 'core/heading', 'attrs' => array( 'level' => 3, 'textAlign' => 'center' ), 'html' => sprintf( '<h3 class="has-text-align-center">%s</h3>', esc_html( (string) ( isset( $el['title'] ) ? $el['title'] : '' ) ) ) ),
							array( 'name' => 'core/heading', 'attrs' => array( 'level' => 2, 'textAlign' => 'center' ), 'html' => sprintf( '<h2 class="has-text-align-center">%s</h2>', esc_html( (string) ( isset( $el['price'] ) ? $el['price'] : '' ) ) ) ),
							$list_items ? array( 'name' => 'core/list', 'inner' => $list_items ) : array( 'name' => 'core/paragraph', 'html' => '<p></p>' ),
							array(
								'name'  => 'core/buttons',
								'attrs' => array( 'layout' => array( 'type' => 'flex', 'justifyContent' => 'center' ) ),
								'inner' => array(
									array(
										'name'  => 'core/button',
										'attrs' => array(
											'text'  => (string) ( isset( $el['button'] ) ? $el['button'] : '' ),
											'url'   => '#contact',
											'style' => array(
												'color'   => array( 'background' => $this->design['colors']['primary'], 'text' => '#ffffff' ),
												'border'  => array( 'radius' => $this->design['buttons']['radius'] ),
											),
										),
										'html'  => sprintf(
											'<div class="wp-block-button"><a class="wp-block-button__link wp-element-button" href="#contact">%s</a></div>',
											esc_html( (string) ( isset( $el['button'] ) ? $el['button'] : '' ) )
										),
									),
								),
							),
						),
					),
				);

			case 'qa':
				return array(
					array(
						'name'  => 'core/group',
						'attrs' => array( 'style' => array( 'spacing' => array( 'padding' => array( 'bottom' => $this->design['spacing']['md'] ) ) ) ),
						'inner' => array(
							array( 'name' => 'core/heading', 'attrs' => array( 'level' => 3 ), 'html' => sprintf( '<h3>%s</h3>', esc_html( (string) ( isset( $el['q'] ) ? $el['q'] : '' ) ) ) ),
							array( 'name' => 'core/paragraph', 'html' => sprintf( '<p>%s</p>', esc_html( (string) ( isset( $el['a'] ) ? $el['a'] : '' ) ) ) ),
						),
					),
				);

			case 'html':
				$html = (string) ( isset( $el['html'] ) ? $el['html'] : '' );
				if ( '' === trim( $html ) ) {
					return array();
				}
				return array(
					array( 'name' => 'core/html', 'html' => $html ),
				);

			case 'navigation':
				$menu = (string) ( isset( $el['menu'] ) ? $el['menu'] : '' );
				$items = array();
				if ( '' !== $menu ) {
					$found = wp_get_nav_menu_object( $menu );
					if ( $found ) {
						$links = wp_get_nav_menu_items( $found->term_id );
						foreach ( (array) $links as $link ) {
							$items[] = array(
								'name'  => 'core/navigation-link',
								'attrs' => array( 'label' => $link->title, 'url' => $link->url ),
							);
						}
					}
				}
				if ( ! $items ) {
					$items = array(
						array( 'name' => 'core/navigation-link', 'attrs' => array( 'label' => __( 'خانه', 'ai-wordpress-copilot' ), 'url' => home_url( '/' ) ) ),
					);
				}
				return array(
					array(
						'name'  => 'core/navigation',
						'attrs' => array( 'layout' => array( 'type' => 'flex', 'justifyContent' => 'left' ) ),
						'inner' => $items,
					),
				);

			case 'nav_links':
				$list = array();
				foreach ( isset( $el['links'] ) ? $el['links'] : array() as $link ) {
					$text = is_array( $link ) ? (string) ( isset( $link['text'] ) ? $link['text'] : '' ) : (string) $link;
					$url  = is_array( $link ) ? (string) ( isset( $link['url'] ) ? $link['url'] : '#' ) : '#';
					$list[] = array( 'name' => 'core/list-item', 'html' => sprintf( '<a href="%s">%s</a>', esc_url( $url ), esc_html( $text ) ) );
				}
				return $list ? array( array( 'name' => 'core/list', 'attrs' => array( 'layout' => array( 'type' => 'flex' ) ), 'inner' => $list ) ) : array();

			case 'link_group':
				$out = array();
				if ( ! empty( $el['title'] ) ) {
					$out[] = array( 'name' => 'core/heading', 'attrs' => array( 'level' => 4 ), 'html' => sprintf( '<h4>%s</h4>', esc_html( (string) $el['title'] ) ) );
				}
				$list = array();
				foreach ( isset( $el['links'] ) ? $el['links'] : array() as $link ) {
					$text = is_array( $link ) ? (string) ( isset( $link['text'] ) ? $link['text'] : '' ) : (string) $link;
					$url  = is_array( $link ) ? (string) ( isset( $link['url'] ) ? $link['url'] : '#' ) : '#';
					$list[] = array( 'name' => 'core/list-item', 'html' => sprintf( '<a href="%s">%s</a>', esc_url( $url ), esc_html( $text ) ) );
				}
				if ( $list ) {
					$out[] = array( 'name' => 'core/list', 'inner' => $list );
				}
				return $out;

			case 'latest_posts':
				return array(
					array(
						'name'  => 'core/latest-posts',
						'attrs' => array(
							'postsToShow' => (int) ( isset( $el['count'] ) ? $el['count'] : 3 ),
							'layout'      => array( 'type' => 'grid', 'columnCount' => 3 ),
						),
					),
				);

			case 'products':
				$count = (int) ( isset( $el['count'] ) ? $el['count'] : 6 );
				$cols  = (int) ( isset( $el['columns'] ) ? $el['columns'] : 3 );
				return array(
					array(
						'name' => 'core/shortcode',
						'html' => sprintf( '[products limit="%d" columns="%d"]', $count, $cols ),
					),
				);

			case 'product_categories':
				return array(
					array(
						'name' => 'core/shortcode',
						'html' => sprintf( '[product_categories columns="3" number="%d"]', (int) ( isset( $el['count'] ) ? $el['count'] : 6 ) ),
					),
				);

			case 'category_card':
				return array(
					array(
						'name'  => 'core/buttons',
						'attrs' => array( 'layout' => array( 'type' => 'flex', 'justifyContent' => 'center' ) ),
						'inner' => array(
							array(
								'name'  => 'core/button',
								'attrs' => array(
									'text'  => (string) ( isset( $el['title'] ) ? $el['title'] : '' ),
									'url'   => (string) ( isset( $el['url'] ) ? $el['url'] : '#' ),
									'style' => array( 'border' => array( 'radius' => $this->design['radius']['md'] ) ),
								),
								'html'  => sprintf(
									'<div class="wp-block-button"><a class="wp-block-button__link wp-element-button" href="%s">%s</a></div>',
									esc_url( (string) ( isset( $el['url'] ) ? $el['url'] : '#' ) ),
									esc_html( (string) ( isset( $el['title'] ) ? $el['title'] : '' ) )
								),
							),
						),
					),
				);

			default:
				return array(
					array( 'name' => 'core/paragraph', 'attrs' => array( 'content' => '' ) ),
				);
		}
	}

	/*
	|--------------------------------------------------------------------------
	| Page + structural editing
	|--------------------------------------------------------------------------
	*/

	/**
	 * Create a full page from section specs.
	 *
	 * @param string $title    Title.
	 * @param array  $specs    Section specs.
	 * @param array  $args     post_status, slug, builder...
	 * @return int|\WP_Error Post ID.
	 */
	public function create_page( $title, array $specs, array $args = array() ) {
		$content = $this->render_sections( $specs );
		$valid   = self::validate_markup( $content );
		if ( is_wp_error( $valid ) ) {
			return $valid;
		}
		$postarr = array(
			'post_title'   => (string) $title,
			'post_content' => $content,
			'post_status'  => isset( $args['post_status'] ) ? (string) $args['post_status'] : 'publish',
			'post_type'    => isset( $args['post_type'] ) ? (string) $args['post_type'] : 'page',
		);
		if ( ! empty( $args['slug'] ) ) {
			$postarr['post_name'] = sanitize_title( (string) $args['slug'] );
		}
		$id = wp_insert_post( $postarr, true );
		if ( is_wp_error( $id ) ) {
			return $id;
		}
		return (int) $id;
	}

	/**
	 * Get top-level blocks of a page.
	 *
	 * @param int $post_id Post ID.
	 * @return array[]|WP_Error parse_blocks() entries (top-level).
	 */
	public function get_blocks( $post_id ) {
		$post = get_post( (int) $post_id );
		if ( ! $post ) {
			return new \WP_Error( 'aiwc_post_not_found', __( 'Post not found.', 'ai-wordpress-copilot' ) );
		}
		$parsed = parse_blocks( $post->post_content );
		$out    = array();
		foreach ( $parsed as $b ) {
			if ( isset( $b['blockName'] ) && null !== $b['blockName'] ) {
				$out[] = $b;
			}
		}
		return $out;
	}

	/**
	 * Delete a top-level block by index.
	 *
	 * @param int $post_id Post ID.
	 * @param int $index   Top-level block index.
	 * @return true|\WP_Error
	 */
	public function delete_block( $post_id, $index ) {
		$blocks = $this->get_blocks( $post_id );
		if ( is_wp_error( $blocks ) ) {
			return $blocks;
		}
		if ( ! isset( $blocks[ $index ] ) ) {
			return new \WP_Error( 'aiwc_block_index', __( 'Block index out of range.', 'ai-wordpress-copilot' ) );
		}
		array_splice( $blocks, $index, 1 );
		return $this->save_blocks( $post_id, $blocks );
	}

	/**
	 * Move a top-level block to a new position.
	 *
	 * @param int $post_id Post ID.
	 * @param int $from    Source index.
	 * @param int $to      Target index.
	 * @return true|\WP_Error
	 */
	public function move_block( $post_id, $from, $to ) {
		$blocks = $this->get_blocks( $post_id );
		if ( is_wp_error( $blocks ) ) {
			return $blocks;
		}
		$n = count( $blocks );
		if ( ! isset( $blocks[ $from ] ) || $to < 0 || $to >= $n ) {
			return new \WP_Error( 'aiwc_block_index', __( 'Block index out of range.', 'ai-wordpress-copilot' ) );
		}
		$block = $blocks[ $from ];
		array_splice( $blocks, $from, 1 );
		array_splice( $blocks, $to, 0, array( $block ) );
		return $this->save_blocks( $post_id, $blocks );
	}

	/**
	 * Update attributes/content of a top-level block.
	 *
	 * @param int   $post_id Post ID.
	 * @param int   $index   Block index.
	 * @param array $attrs   Attributes to merge.
	 * @param string|null $content Optional raw inner content (paragraph/heading text).
	 * @return true|\WP_Error
	 */
	public function update_block( $post_id, $index, array $attrs, $content = null ) {
		$blocks = $this->get_blocks( $post_id );
		if ( is_wp_error( $blocks ) ) {
			return $blocks;
		}
		if ( ! isset( $blocks[ $index ] ) ) {
			return new \WP_Error( 'aiwc_block_index', __( 'Block index out of range.', 'ai-wordpress-copilot' ) );
		}
		$blocks[ $index ]['attrs'] = array_merge( $blocks[ $index ]['attrs'], $attrs );
		if ( null !== $content ) {
			$blocks[ $index ]['innerHTML'] = esc_html( (string) $content );
			$blocks[ $index ]['innerContent'] = array( esc_html( (string) $content ) );
		}
		return $this->save_blocks( $post_id, $blocks );
	}

	/**
	 * Wrap several top-level blocks in a core/group.
	 *
	 * @param int   $post_id Post ID.
	 * @param int[] $indexes Block indexes (ascending).
	 * @return true|\WP_Error
	 */
	public function wrap_in_group( $post_id, array $indexes ) {
		$blocks = $this->get_blocks( $post_id );
		if ( is_wp_error( $blocks ) ) {
			return $blocks;
		}
		$indexes = array_values( array_unique( array_map( 'intval', $indexes ) ) );
		sort( $indexes );
		foreach ( $indexes as $i ) {
			if ( ! isset( $blocks[ $i ] ) ) {
				return new \WP_Error( 'aiwc_block_index', __( 'Block index out of range.', 'ai-wordpress-copilot' ) );
			}
		}
		if ( ! $indexes ) {
			return new \WP_Error( 'aiwc_block_index', __( 'No blocks selected.', 'ai-wordpress-copilot' ) );
		}
		$selected = array();
		foreach ( $indexes as $i ) {
			$selected[] = $blocks[ $i ];
		}
		$group = array(
			'blockName'    => 'core/group',
			'attrs'        => array( 'layout' => array( 'type' => 'constrained', 'contentSize' => $this->design['container']['width'] ) ),
			'innerBlocks'  => $selected,
			'innerContent' => array_fill( 0, count( $selected ), null ),
			'innerHTML'    => '',
		);
		// Remove originals (descending) and insert group at first index.
		foreach ( array_reverse( $indexes ) as $i ) {
			array_splice( $blocks, $i, 1 );
		}
		array_splice( $blocks, $indexes[0], 0, array( $group ) );
		return $this->save_blocks( $post_id, $blocks );
	}

	/**
	 * Insert a core/columns block holding the given column contents.
	 *
	 * @param int    $post_id  Post ID.
	 * @param int    $at_index Insert position.
	 * @param array  $columns  Each entry: list of block arrays (or strings → paragraphs).
	 * @return true|\WP_Error
	 */
	public function add_columns( $post_id, $at_index, array $columns ) {
		$blocks = $this->get_blocks( $post_id );
		if ( is_wp_error( $blocks ) ) {
			return $blocks;
		}
		$at_index = max( 0, min( count( $blocks ), (int) $at_index ) );
		$col_blocks = array();
		foreach ( array_slice( $columns, 0, 6 ) as $col ) {
			$inner = array();
			foreach ( (array) $col as $b ) {
				if ( is_string( $b ) ) {
					$inner[] = array( 'blockName' => 'core/paragraph', 'attrs' => array( 'content' => $b ), 'innerBlocks' => array(), 'innerContent' => array( esc_html( $b ) ), 'innerHTML' => esc_html( $b ) );
				} elseif ( is_array( $b ) ) {
					$inner[] = $b;
				}
			}
			$col_blocks[] = array(
				'blockName'    => 'core/column',
				'attrs'        => array( 'width' => floor( 100 / max( 1, count( $columns ) ) ) . '%' ),
				'innerBlocks'  => $inner,
				'innerContent' => array_fill( 0, count( $inner ), null ),
				'innerHTML'    => '',
			);
		}
		$columns_block = array(
			'blockName'    => 'core/columns',
			'attrs'        => array(),
			'innerBlocks'  => $col_blocks,
			'innerContent' => array_fill( 0, count( $col_blocks ), null ),
			'innerHTML'    => '',
		);
		array_splice( $blocks, $at_index, 0, array( $columns_block ) );
		return $this->save_blocks( $post_id, $blocks );
	}

	/**
	 * Replace the whole block list of a page.
	 *
	 * @param int   $post_id Post ID.
	 * @param array $blocks  parse_blocks()-shaped list.
	 * @return true|\WP_Error
	 */
	public function save_blocks( $post_id, array $blocks ) {
		$content = '';
		foreach ( $blocks as $b ) {
			$content .= serialize_block( $b );
		}
		$valid = self::validate_markup( $content );
		if ( is_wp_error( $valid ) ) {
			return $valid;
		}
		$r = wp_update_post(
			array(
				'ID'           => (int) $post_id,
				'post_content' => $content,
			),
			true
		);
		return is_wp_error( $r ) ? $r : true;
	}

	/**
	 * Validate block markup: balanced block comments + every block registered.
	 *
	 * @param string $content Block markup.
	 * @return true|\WP_Error
	 */
	public static function validate_markup( $content ) {
		$content = (string) $content;
		if ( '' === trim( $content ) ) {
			return true;
		}
		$opens     = preg_match_all( '/<!--\s+wp:/', $content );
		$self_close = preg_match_all( '/<!--\s+wp:[^>]*\/-->/s', $content );
		$closes    = preg_match_all( '/<!--\s+\/wp:/', $content );
		if ( ( $opens - $self_close ) !== $closes ) {
			return new \WP_Error(
				'aiwc_blocks_unbalanced',
				sprintf( 'Block markup is unbalanced (%d open vs %d close).', $opens - $self_close, $closes )
			);
		}
		preg_match_all( '/<!--\s+wp:([a-z0-9\/-]+)/', $content, $m );
		foreach ( array_unique( $m[1] ) as $name ) {
			$full = 0 === strpos( $name, 'core/' ) ? $name : 'core/' . $name;
			if ( !\WP_Block_Type_Registry::get_instance()->is_registered( $full ) && !\WP_Block_Type_Registry::get_instance()->is_registered( $name ) ) {
				return new \WP_Error( 'aiwc_blocks_unknown', sprintf( 'Unknown block: %s', $name ) );
			}
		}
		return true;
	}
}
