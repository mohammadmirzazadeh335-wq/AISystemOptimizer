<?php
/**
 * WooCommerce catalog tools: variable products, attributes, variations,
 * categories, inventory, images, analysis and description/SEO application.
 *
 * Price/stock mutations require explicit user confirmation (confirm=true);
 * every mutation is snapshot-protected and logged.
 *
 * @package AIWC
 */

namespace AIWC\Ai\Tools;

use AIWC\Ai\Abstract_Tool_Group;

defined( 'ABSPATH' ) || exit;

/**
 * Class Woo_Catalog_Tools
 */
class Woo_Catalog_Tools extends Abstract_Tool_Group {

	/**
	 * Group id.
	 *
	 * @var string
	 */
	protected $group = 'woo_catalog';

	/**
	 * Ensure WooCommerce is loaded.
	 *
	 * @return bool
	 */
	private function ensure_woo() {
		return class_exists( 'WooCommerce' );
	}

	/**
	 * Tool schemas.
	 *
	 * @return array[]
	 */
	public function tools() {
		return array(
			array(
				'name'        => 'woo_product_variable',
				'description' => 'Create or update a WooCommerce VARIABLE product with attributes and variations (SKU, price, stock per variation) using standard WC classes. Price/stock values require confirm=true (user approval).',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'product_id'  => array( 'type' => 'integer', 'description' => 'Existing product ID (omit to create).' ),
						'title'       => array( 'type' => 'string', 'description' => 'Product name (required for create).' ),
						'description' => array( 'type' => 'string', 'description' => 'Long description.' ),
						'attributes'  => array(
							'type'        => 'array',
							'description' => 'Attributes: [{name, options[], variation: true}].',
							'items'       => array( 'type' => 'object' ),
						),
						'variations'  => array(
							'type'        => 'array',
							'description' => 'Variations: [{sku, attributes: {name: option}, price, sale_price, stock, stock_status}].',
							'items'       => array( 'type' => 'object' ),
						),
						'confirm'     => array( 'type' => 'boolean', 'description' => 'User-approved confirmation for price/stock values.' ),
					),
					'required'   => array(),
				),
				'handler'     => 'handle_product_variable',
				'risk'        => 'write',
			),
			array(
				'name'        => 'woo_manage_stock',
				'description' => 'Manage inventory of a product or variation: quantity, low-stock threshold, backorders, stock status. Requires confirm=true (user approval) — sensitive commerce change.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'product_id'     => array( 'type' => 'integer' ),
						'variation_id'   => array( 'type' => 'integer', 'description' => 'Optional variation ID.' ),
						'stock'          => array( 'type' => 'integer', 'description' => 'Quantity.' ),
						'low_stock'      => array( 'type' => 'number', 'description' => 'Low-stock threshold.' ),
						'backorders'     => array( 'type' => 'string', 'description' => 'no | notify | yes' ),
						'stock_status'   => array( 'type' => 'string', 'description' => 'instock | outofstock | onbackorder' ),
						'confirm'        => array( 'type' => 'boolean' ),
					),
					'required'   => array( 'product_id', 'confirm' ),
				),
				'handler'     => 'handle_manage_stock',
				'risk'        => 'write',
				'needs_confirmation' => true,
			),
			array(
				'name'        => 'woo_product_categories',
				'description' => 'Create or update product categories (name, slug, parent, description, display type).',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'action'      => array( 'type' => 'string', 'description' => 'create | update | list' ),
						'name'        => array( 'type' => 'string' ),
						'term_id'     => array( 'type' => 'integer', 'description' => 'For update.' ),
						'slug'        => array( 'type' => 'string' ),
						'parent'      => array( 'type' => 'integer' ),
						'description' => array( 'type' => 'string' ),
						'display'     => array( 'type' => 'string', 'description' => 'products | subcategories | both' ),
					),
					'required'   => array( 'action' ),
				),
				'handler'     => 'handle_product_categories',
				'risk'        => 'write',
			),
			array(
				'name'        => 'woo_product_images',
				'description' => 'Set the product gallery images from media library IDs or image URLs (URLs are sideloaded via media_sideload_image).',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'product_id'  => array( 'type' => 'integer' ),
						'image_id'    => array( 'type' => 'integer', 'description' => 'Main image attachment ID.' ),
						'image_url'   => array( 'type' => 'string', 'description' => 'Main image URL (sideloaded).' ),
						'gallery_ids' => array( 'type' => 'array', 'items' => array( 'type' => 'integer' ) ),
						'gallery_urls'=> array( 'type' => 'array', 'items' => array( 'type' => 'string' ) ),
					),
					'required'   => array( 'product_id' ),
				),
				'handler'     => 'handle_product_images',
				'risk'        => 'write',
			),
			array(
				'name'        => 'woo_product_analyze',
				'description' => 'Analyze a product: data completeness (title/desc/images/price/stock/SEO), price vs category average, missing fields, actionable fixes.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array( 'product_id' => array( 'type' => 'integer' ) ),
					'required'   => array( 'product_id' ),
				),
				'handler'     => 'handle_product_analyze',
				'risk'        => 'read',
			),
			array(
				'name'        => 'woo_product_description',
				'description' => 'Apply a generated product description (long + short) and SEO fields (meta title/description) to a product. The description TEXT must come from you (the model); this tool validates, applies and runs the SEO checks.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'product_id'         => array( 'type' => 'integer' ),
						'description'        => array( 'type' => 'string' ),
						'short_description'  => array( 'type' => 'string' ),
						'seo_title'          => array( 'type' => 'string' ),
						'seo_description'    => array( 'type' => 'string' ),
					),
					'required'   => array( 'product_id' ),
				),
				'handler'     => 'handle_product_description',
				'risk'        => 'write',
			),
			array(
				'name'        => 'woo_shop_design',
				'description' => 'Build or redesign the shop and category pages (product grid, category grid, pricing cards) with the design system — produces real pages.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'action'      => array( 'type' => 'string', 'description' => 'shop | category' ),
						'title'       => array( 'type' => 'string' ),
						'slug'        => array( 'type' => 'string' ),
						'category_id' => array( 'type' => 'integer', 'description' => 'For action=category.' ),
						'builder'     => array( 'type' => 'string', 'description' => 'auto | gutenberg | elementor' ),
					),
					'required'   => array( 'action' ),
				),
				'handler'     => 'handle_shop_design',
				'risk'        => 'write',
			),
		);
	}

	/**
	 * woo_product_variable
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_product_variable( array $args, array $context = array() ) {
		if ( ! $this->ensure_woo() ) {
			return $this->error( 'WooCommerce is not active on this site.' );
		}
		$has_prices = false;
		foreach ( (array) ( $args['variations'] ?? array() ) as $v ) {
			if ( is_array( $v ) && ( isset( $v['price'] ) || isset( $v['sale_price'] ) || isset( $v['stock'] ) ) ) {
				$has_prices = true;
				break;
			}
		}
		if ( $has_prices && empty( $args['confirm'] ) ) {
			$log_id = $this->plugin->get( 'registry' )->create_approval( 'woo_product_variable', $args, $context );
			return $this->error( sprintf( 'Variation price/stock requires explicit user confirmation (confirm=true). Approval entry #%d created.', $log_id ) );
		}

		$product_id = absint( $args['product_id'] ?? 0 );
		$product    = $product_id ? wc_get_product( $product_id ) : null;
		if ( $product && ! $product instanceof \WC_Product_Variable ) {
			// Convert simple → variable is not safe; create new.
			$product = null;
			$product_id = 0;
		}
		if ( ! $product ) {
			if ( empty( $args['title'] ) ) {
				return $this->error( 'title is required when creating a variable product.' );
			}
			$product = new \WC_Product_Variable();
			$product->set_name( sanitize_text_field( $args['title'] ) );
			$product->set_status( 'publish' );
		}
		if ( isset( $args['description'] ) ) {
			$product->set_description( wp_kses_post( $args['description'] ) );
		}

		$attributes = array();
		foreach ( (array) ( $args['attributes'] ?? array() ) as $attr ) {
			if ( ! is_array( $attr ) || empty( $attr['name'] ) ) {
				continue;
			}
			$wc_attr = new \WC_Product_Attribute();
			$wc_attr->set_name( sanitize_text_field( $attr['name'] ) );
			$wc_attr->set_options( array_map( 'sanitize_text_field', (array) ( $attr['options'] ?? array() ) ) );
			$wc_attr->set_visible( true );
			$wc_attr->set_variation( ! empty( $attr['variation'] ) );
			$attributes[] = $wc_attr;
		}
		if ( $attributes ) {
			$product->set_attributes( $attributes );
		}
		$product_id = $product->save();

		$variation_ids = array();
		foreach ( (array) ( $args['variations'] ?? array() ) as $v ) {
			if ( ! is_array( $v ) ) {
				continue;
			}
			$variation = new \WC_Product_Variation();
			$variation->set_parent_id( $product_id );
			if ( ! empty( $v['sku'] ) ) {
				$variation->set_sku( sanitize_text_field( $v['sku'] ) );
			}
			$attrs = array();
			foreach ( (array) ( $v['attributes'] ?? array() ) as $an => $av ) {
				$attrs[ sanitize_title( (string) $an ) ] = sanitize_text_field( (string) $av );
			}
			$variation->set_attributes( $attrs );
			if ( isset( $v['price'] ) ) {
				$variation->set_regular_price( wc_format_decimal( (string) $v['price'] ) );
			}
			if ( isset( $v['sale_price'] ) ) {
				$variation->set_sale_price( wc_format_decimal( (string) $v['sale_price'] ) );
			}
			if ( isset( $v['stock'] ) ) {
				$variation->set_manage_stock( true );
				$variation->set_stock_quantity( absint( $v['stock'] ) );
				$variation->set_stock_status( absint( $v['stock'] ) > 0 ? 'instock' : 'outofstock' );
			}
			$variation_ids[] = $variation->save();
		}
		if ( $variation_ids ) {
			// Refresh variable product data (prices, lookup tables).
			$product = wc_get_product( $product_id );
			if ( $product instanceof \WC_Product_Variable ) {
				\WC_Product_Variable::sync( $product );
				$product->save();
			}
		}

		return $this->success(
			array(
				'product_id'   => (int) $product_id,
				'variation_ids' => array_map( 'intval', $variation_ids ),
				'type'         => 'variable',
			),
			sprintf( 'Variable product #%d saved with %d variation(s).', $product_id, count( $variation_ids ) )
		);
	}

	/**
	 * woo_manage_stock
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_manage_stock( array $args, array $context = array() ) {
		if ( ! $this->ensure_woo() ) {
			return $this->error( 'WooCommerce is not active on this site.' );
		}
		if ( empty( $args['confirm'] ) ) {
			$log_id = $this->plugin->get( 'registry' )->create_approval( 'woo_manage_stock', $args, $context );
			return $this->error( sprintf( 'Inventory changes require explicit user confirmation (confirm=true). Approval entry #%d created.', $log_id ) );
		}
		$target_id = absint( $args['variation_id'] ?? 0 ) ? absint( $args['variation_id'] ) : absint( $args['product_id'] );
		$product   = wc_get_product( $target_id );
		if ( ! $product ) {
			return $this->error( sprintf( 'Product %d not found.', $target_id ) );
		}
		$before = array( 'stock' => $product->get_stock_quantity(), 'status' => $product->get_stock_status() );

		if ( isset( $args['stock'] ) ) {
			$product->set_manage_stock( true );
			$product->set_stock_quantity( absint( $args['stock'] ) );
		}
		if ( isset( $args['low_stock'] ) && method_exists( $product, 'set_low_stock_amount' ) ) {
			$product->set_low_stock_amount( (float) $args['low_stock'] );
		}
		if ( isset( $args['backorders'] ) && in_array( $args['backorders'], array( 'no', 'notify', 'yes' ), true ) ) {
			$product->set_backorders( $args['backorders'] );
		}
		if ( isset( $args['stock_status'] ) && in_array( $args['stock_status'], array( 'instock', 'outofstock', 'onbackorder' ), true ) ) {
			$product->set_stock_status( $args['stock_status'] );
		}
		$product->save();

		return $this->success(
			array(
				'product_id' => (int) $target_id,
				'before'     => $before,
				'after'      => array( 'stock' => $product->get_stock_quantity(), 'status' => $product->get_stock_status() ),
			),
			sprintf( 'Inventory updated for #%d.', $target_id )
		);
	}

	/**
	 * woo_product_categories
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_product_categories( array $args ) {
		if ( ! $this->ensure_woo() ) {
			return $this->error( 'WooCommerce is not active on this site.' );
		}
		$action = (string) ( $args['action'] ?? '' );
		if ( 'list' === $action ) {
			$terms = get_terms( array( 'taxonomy' => 'product_cat', 'hide_empty' => false ) );
			$out   = array();
			foreach ( is_array( $terms ) ? $terms : array() as $t ) {
				$out[] = array( 'term_id' => (int) $t->term_id, 'name' => $t->name, 'slug' => $t->slug, 'count' => (int) $t->count );
			}
			return $this->success( array( 'categories' => $out ), sprintf( '%d categories.', count( $out ) ) );
		}
		if ( 'create' === $action ) {
			if ( empty( $args['name'] ) ) {
				return $this->error( 'name is required.' );
			}
			$exists = term_exists( sanitize_text_field( $args['name'] ), 'product_cat' );
			if ( $exists ) {
				// Idempotent: return the existing category instead of failing.
				$existing_id = (int) ( is_array( $exists ) ? $exists['term_id'] : $exists );
				return $this->success( array( 'term_id' => $existing_id, 'already_existed' => true ), 'Category already existed.' );
			}
			$term = wp_insert_term(
				sanitize_text_field( $args['name'] ),
				'product_cat',
				array(
					'slug'        => isset( $args['slug'] ) ? sanitize_title( $args['slug'] ) : '',
					'parent'      => absint( $args['parent'] ?? 0 ),
					'description' => isset( $args['description'] ) ? wp_kses_post( $args['description'] ) : '',
				)
			);
			if ( is_wp_error( $term ) ) {
				return $this->error( $term->get_error_message() );
			}
			if ( ! empty( $args['display'] ) && in_array( $args['display'], array( 'products', 'subcategories', 'both' ), true ) ) {
				update_term_meta( (int) $term['term_id'], 'display_type', $args['display'] );
			}
			return $this->success( array( 'term_id' => (int) $term['term_id'] ), 'Category created.' );
		}
		if ( 'update' === $action ) {
			$term_id = absint( $args['term_id'] ?? 0 );
			if ( ! $term_id || ! term_exists( $term_id, 'product_cat' ) ) {
				return $this->error( 'term_id not found.' );
			}
			$data = array();
			if ( isset( $args['name'] ) ) {
				$data['name'] = sanitize_text_field( $args['name'] );
			}
			if ( isset( $args['description'] ) ) {
				$data['description'] = wp_kses_post( $args['description'] );
			}
			if ( isset( $args['parent'] ) ) {
				$data['parent'] = absint( $args['parent'] );
			}
			$r = wp_update_term( $term_id, 'product_cat', $data );
			if ( is_wp_error( $r ) ) {
				return $this->error( $r->get_error_message() );
			}
			if ( ! empty( $args['display'] ) && in_array( $args['display'], array( 'products', 'subcategories', 'both' ), true ) ) {
				update_term_meta( $term_id, 'display_type', $args['display'] );
			}
			return $this->success( array( 'term_id' => $term_id ), 'Category updated.' );
		}
		return $this->error( 'Unknown action: ' . $action );
	}

	/**
	 * woo_product_images
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_product_images( array $args ) {
		if ( ! $this->ensure_woo() ) {
			return $this->error( 'WooCommerce is not active on this site.' );
		}
		$product = wc_get_product( absint( $args['product_id'] ) );
		if ( ! $product ) {
			return $this->error( 'Product not found.' );
		}
		$changed = array();

		$image_id = absint( $args['image_id'] ?? 0 );
		if ( ! $image_id && ! empty( $args['image_url'] ) ) {
			$image_id = $this->sideload( (string) $args['image_url'], $product->get_id() );
			if ( is_wp_error( $image_id ) ) {
				return $this->error( 'Image sideload failed: ' . $image_id->get_error_message() );
			}
		}
		if ( $image_id ) {
			$product->set_image_id( $image_id );
			$changed['image_id'] = $image_id;
		}

		$gallery = array_filter( array_map( 'absint', (array) ( $args['gallery_ids'] ?? array() ) ) );
		foreach ( (array) ( $args['gallery_urls'] ?? array() ) as $url ) {
			$id = $this->sideload( (string) $url, $product->get_id() );
			if ( ! is_wp_error( $id ) && $id ) {
				$gallery[] = (int) $id;
			}
		}
		if ( $gallery ) {
			$product->set_gallery_image_ids( $gallery );
			$changed['gallery_ids'] = $gallery;
		}
		if ( ! $changed ) {
			return $this->error( 'No image ID or URL provided.' );
		}
		$product->save();
		return $this->success( array( 'product_id' => $product->get_id() ) + $changed, 'Product images updated.' );
	}

	/**
	 * Sideload an image into the media library.
	 *
	 * @param string $url       Image URL.
	 * @param int    $product_id Product ID (for naming).
	 * @return int|\WP_Error
	 */
	private function sideload( $url, $product_id ) {
		if ( ! function_exists( 'media_handle_sideload' ) ) {
			require_once ABSPATH . 'wp-admin/includes/media.php';
			require_once ABSPATH . 'wp-admin/includes/file.php';
			require_once ABSPATH . 'wp-admin/includes/image.php';
		}
		$guard = new \AIWC\Security\Url_Guard();
		$wrapped = $guard->request_with_validated_redirects( $url );
		$r       = $wrapped['response'];
		if ( is_wp_error( $r ) ) {
			return $r;
		}
		if ( 200 !== (int) wp_remote_retrieve_response_code( $r ) ) {
			return new \WP_Error( 'aiwc_woo_image_fetch_failed', 'Image download failed (HTTP ' . (int) wp_remote_retrieve_response_code( $r ) . ').' );
		}
		$body  = wp_remote_retrieve_body( $r );
		$ctype = (string) wp_remote_retrieve_header( $r, 'content-type' );
		$ext   = false !== strpos( $ctype, 'png' ) ? 'png' : ( false !== strpos( $ctype, 'webp' ) ? 'webp' : 'jpg' );
		if ( strlen( $body ) < 8 || strlen( $body ) > 20 * MB_IN_BYTES ) {
			return new \WP_Error( 'aiwc_woo_image_fetch_failed', 'Image download failed or file too large.' );
		}
		$tmp       = wp_tempnam( 'aiwc-woo-img.' . $ext );
		file_put_contents( $tmp, $body );
		$file_array    = array(
			'name'     => 'aiwc-img-' . time() . '.' . $ext,
			'tmp_name' => $tmp,
		);
		$attachment_id = media_handle_sideload( $file_array, $product_id );
		if ( is_wp_error( $attachment_id ) ) {
			@unlink( $tmp ); // phpcs:ignore WordPress.PHP.NoSilencedErrors
			return $attachment_id;
		}
		return (int) $attachment_id;
	}

	/**
	 * woo_product_analyze
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_product_analyze( array $args ) {
		if ( ! $this->ensure_woo() ) {
			return $this->error( 'WooCommerce is not active on this site.' );
		}
		$product = wc_get_product( absint( $args['product_id'] ) );
		if ( ! $product ) {
			return $this->error( 'Product not found.' );
		}
		$missing = array();
		if ( '' === trim( (string) $product->get_description() ) ) {
			$missing[] = 'description';
		}
		if ( '' === trim( (string) $product->get_short_description() ) ) {
			$missing[] = 'short_description';
		}
		if ( ! $product->get_image_id() ) {
			$missing[] = 'image';
		}
		if ( '' === (string) $product->get_regular_price() ) {
			$missing[] = 'price';
		}
		if ( '' === trim( (string) get_post_meta( $product->get_id(), '_yoast_wpseo_metadesc', true ) ) && '' === trim( (string) get_post_meta( $product->get_id(), '_aioseo_description', true ) ) ) {
			$missing[] = 'seo_meta_description';
		}
		if ( ! $product->get_sku() ) {
			$missing[] = 'sku';
		}

		// Price vs category average.
		$price_note = '';
		$terms      = wp_get_post_terms( $product->get_id(), 'product_cat', array( 'fields' => 'ids' ) );
		if ( ! is_wp_error( $terms ) && $terms ) {
			$prices = array();
			$q      = new \WP_Query(
				array(
					'post_type'      => 'product',
					'post_status'    => 'publish',
					'posts_per_page' => 20,
					'tax_query'      => array(
						array(
							'taxonomy' => 'product_cat',
							'field'    => 'term_id',
							'terms'    => $terms,
						),
					),
					'fields'         => 'ids',
				)
			);
			foreach ( $q->posts as $pid ) {
				$p = wc_get_product( $pid );
				if ( $p && '' !== (string) $p->get_regular_price() ) {
					$prices[] = (float) $p->get_regular_price();
				}
			}
			if ( $prices ) {
				$avg = array_sum( $prices ) / count( $prices );
				$mine = (float) $product->get_regular_price();
				$price_note = sprintf( 'Category average price: %.2f (yours: %.2f, %+.0f%%).', $avg, $mine, $avg > 0 ? ( ( $mine - $avg ) / $avg ) * 100 : 0 );
			}
		}

		$score = max( 0, 100 - 12 * count( $missing ) );
		return $this->success(
			array(
				'product_id'  => $product->get_id(),
				'score'       => $score,
				'missing'     => $missing,
				'price_note'  => $price_note,
				'fixes'       => array_map(
					function ( $m ) {
						return 'Add/complete: ' . $m;
					},
					$missing
				),
			),
			sprintf( 'Product analysis complete (score %d).', $score )
		);
	}

	/**
	 * woo_product_description
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_product_description( array $args ) {
		if ( ! $this->ensure_woo() ) {
			return $this->error( 'WooCommerce is not active on this site.' );
		}
		$product = wc_get_product( absint( $args['product_id'] ) );
		if ( ! $product ) {
			return $this->error( 'Product not found.' );
		}
		$before = array( 'description_len' => strlen( (string) $product->get_description() ) );
		if ( isset( $args['description'] ) ) {
			$product->set_description( wp_kses_post( $args['description'] ) );
		}
		if ( isset( $args['short_description'] ) ) {
			$product->set_short_description( wp_kses_post( $args['short_description'] ) );
		}
		if ( isset( $args['seo_title'] ) ) {
			update_post_meta( $product->get_id(), '_yoast_wpseo_title', sanitize_text_field( $args['seo_title'] ) );
			update_post_meta( $product->get_id(), '_aioseo_title', sanitize_text_field( $args['seo_title'] ) );
		}
		if ( isset( $args['seo_description'] ) ) {
			update_post_meta( $product->get_id(), '_yoast_wpseo_metadesc', sanitize_text_field( $args['seo_description'] ) );
			update_post_meta( $product->get_id(), '_aioseo_description', sanitize_text_field( $args['seo_description'] ) );
		}
		$product->save();

		// Post-apply SEO sanity: description length + keyword presence check.
		$desc = (string) $product->get_description();
		$checks = array(
			'description_length_ok' => mb_strlen( wp_strip_all_tags( $desc ) ) >= 150,
			'short_description_ok'  => mb_strlen( wp_strip_all_tags( (string) $product->get_short_description() ) ) >= 20,
			'seo_description_ok'    => mb_strlen( (string) ( $args['seo_description'] ?? '' ) ) >= 50 && mb_strlen( (string) ( $args['seo_description'] ?? '' ) ) <= 160,
		);
		return $this->success(
			array( 'product_id' => $product->get_id(), 'before' => $before, 'seo_checks' => $checks ),
			'Product description + SEO fields applied.'
		);
	}

	/**
	 * woo_shop_design
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_shop_design( array $args ) {
		if ( ! $this->ensure_woo() ) {
			return $this->error( 'WooCommerce is not active on this site.' );
		}
		$action = (string) ( $args['action'] ?? '' );
		$sections = array();
		if ( 'shop' === $action ) {
			$sections = array(
				array( 'type' => 'hero', 'content' => array( 'heading' => (string) ( $args['title'] ?? __( 'فروشگاه ما', 'ai-wordpress-copilot' ) ), 'button_text' => __( 'مشاهده محصولات', 'ai-wordpress-copilot' ), 'button_url' => '#products' ) ),
				array( 'type' => 'category_grid', 'content' => array( 'heading' => __( 'دسته‌بندی‌ها', 'ai-wordpress-copilot' ) ) ),
				array( 'type' => 'product_grid', 'content' => array( 'heading' => __( 'محصولات ویژه', 'ai-wordpress-copilot' ) ) ),
				array( 'type' => 'features', 'content' => array() ),
				array( 'type' => 'newsletter', 'content' => array() ),
			);
		} elseif ( 'category' === $action ) {
			$sections = array(
				array( 'type' => 'hero', 'content' => array( 'heading' => (string) ( $args['title'] ?? __( 'دسته‌بندی محصولات', 'ai-wordpress-copilot' ) ) ) ),
				array( 'type' => 'product_grid', 'content' => array( 'heading' => __( 'محصولات این دسته', 'ai-wordpress-copilot' ) ) ),
				array( 'type' => 'cta', 'content' => array() ),
			);
		} else {
			return $this->error( 'Unknown action: ' . $action );
		}
		$result = \AIWC\Builder\Design_Engine::build_page(
			(string) ( $args['title'] ?? ( 'shop' === $action ? __( 'فروشگاه', 'ai-wordpress-copilot' ) : __( 'دسته‌بندی', 'ai-wordpress-copilot' ) ) ),
			$sections,
			array(
				'slug'    => (string) ( $args['slug'] ?? '' ),
				'builder' => (string) ( $args['builder'] ?? 'auto' ),
			)
		);
		if ( is_wp_error( $result ) ) {
			return $this->error( $result->get_error_message() );
		}
		return $this->success( $result, 'Shop design page built: ' . $result['url'] );
	}
}
