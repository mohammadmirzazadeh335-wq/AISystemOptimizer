<?php
/**
 * WooCommerce tools (available only when WooCommerce is active).
 *
 * @package AIWC
 */

namespace AIWC\Ai\Tools;

use AIWC\Ai\Abstract_Tool_Group;

defined( 'ABSPATH' ) || exit;

/**
 * Product management and store analysis tools.
 */
class Woo_Tools extends Abstract_Tool_Group {

	/**
	 * Declare tools.
	 *
	 * @return array[]
	 */
	public function tools() {
		return array(
			array(
				'name'        => 'woo_product_create',
				'description' => 'Create a WooCommerce product: title, description, price, sale price, SKU, stock quantity, categories, status. Only available when WooCommerce is active.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'title'       => array( 'type' => 'string', 'description' => 'Product title.' ),
						'description' => array( 'type' => 'string', 'description' => 'Full product description (HTML allowed).' ),
						'short_description' => array( 'type' => 'string', 'description' => 'Short description.' ),
						'price'       => array( 'type' => 'string', 'description' => 'Regular price, e.g. "29.99".' ),
						'sale_price'  => array( 'type' => 'string', 'description' => 'Optional sale price.' ),
						'sku'         => array( 'type' => 'string', 'description' => 'SKU.' ),
						'stock'       => array( 'type' => 'integer', 'description' => 'Stock quantity.' ),
						'categories'  => array( 'type' => 'array', 'description' => 'Product category names.' ),
						'status'      => array( 'type' => 'string', 'description' => 'publish or draft. Default draft.', 'enum' => array( 'publish', 'draft' ) ),
					),
					'required'   => array( 'title', 'price' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_product_create',
			),
			array(
				'name'        => 'woo_product_update',
				'description' => 'Update an existing WooCommerce product by ID: price, sale price, stock, description, status.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'product_id'  => array( 'type' => 'integer', 'description' => 'Product ID.' ),
						'title'       => array( 'type' => 'string', 'description' => 'New title.' ),
						'description' => array( 'type' => 'string', 'description' => 'New description.' ),
						'price'       => array( 'type' => 'string', 'description' => 'New regular price.' ),
						'sale_price'  => array( 'type' => 'string', 'description' => 'New sale price.' ),
						'stock'       => array( 'type' => 'integer', 'description' => 'New stock quantity.' ),
						'status'      => array( 'type' => 'string', 'description' => 'New status.', 'enum' => array( 'publish', 'draft' ) ),
					),
					'required'   => array( 'product_id' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_product_update',
			),
			array(
				'name'        => 'woo_product_list',
				'description' => 'List WooCommerce products with price, stock and status.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'limit'  => array( 'type' => 'integer', 'description' => 'Max items, default 15.' ),
						'search' => array( 'type' => 'string', 'description' => 'Search term.' ),
					),
				),
				'risk'        => 'read',
				'handler'     => 'handle_product_list',
			),
			array(
				'name'        => 'woo_report',
				'description' => 'Get a store status report: product counts by status, low-stock products, out-of-stock products, top-level categories and general store health.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(),
				),
				'risk'        => 'read',
				'handler'     => 'handle_woo_report',
			),
		);
	}

	/**
	 * Ensure WooCommerce is available.
	 *
	 * @return bool
	 */
	private function ensure_woo() {
		return class_exists( 'WooCommerce' );
	}

	/**
	 * woo_product_create
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_product_create( array $args, array $context = array() ) {
		if ( ! $this->ensure_woo() ) {
			return $this->error( 'WooCommerce is not active on this site.' );
		}

		$status = in_array( $args['status'] ?? 'draft', array( 'publish', 'draft' ), true ) ? $args['status'] : 'draft';
		$props  = array();

		if ( isset( $args['price'] ) && '' !== $args['price'] ) {
			$props['regular_price'] = wc_format_decimal( (string) $args['price'] );
		}
		if ( isset( $args['sale_price'] ) && '' !== $args['sale_price'] ) {
			$props['sale_price'] = wc_format_decimal( (string) $args['sale_price'] );
		}
		if ( isset( $args['sku'] ) && '' !== $args['sku'] ) {
			$props['sku'] = sanitize_text_field( $args['sku'] );
		}
		if ( isset( $args['stock'] ) ) {
			$props['manage_stock'] = true;
			$props['stock_quantity'] = absint( $args['stock'] );
			$props['stock_status'] = absint( $args['stock'] ) > 0 ? 'instock' : 'outofstock';
		}

		$product = new \WC_Product_Simple();
		$product->set_name( sanitize_text_field( $args['title'] ) );
		$product->set_status( $status );
		if ( isset( $args['description'] ) ) {
			$product->set_description( wp_kses_post( $args['description'] ) );
		}
		if ( isset( $args['short_description'] ) ) {
			$product->set_short_description( wp_kses_post( $args['short_description'] ) );
		}
		foreach ( $props as $key => $value ) {
			$setter = 'set_' . $key;
			if ( method_exists( $product, $setter ) ) {
				$product->{$setter}( $value );
			}
		}

		$product_id = $product->save();

		if ( ! empty( $args['categories'] ) && is_array( $args['categories'] ) ) {
			$ids = array();
			foreach ( $args['categories'] as $cat ) {
				$term = term_exists( sanitize_text_field( $cat ), 'product_cat' );
				if ( ! $term ) {
					$term = wp_insert_term( sanitize_text_field( $cat ), 'product_cat' );
				}
				if ( ! is_wp_error( $term ) ) {
					$ids[] = (int) ( is_array( $term ) ? $term['term_id'] : $term );
				}
			}
			wp_set_post_terms( $product_id, $ids, 'product_cat' );
		}

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'woo_product_create',
				'object_type'     => 'post',
				'object_id'       => $product_id,
				'summary'         => sprintf( 'Created product "%s" (#%d)', $args['title'], $product_id ),
				'args'            => $args,
				'after_state'     => $this->plugin->get( 'snapshots' )->capture( 'post', $product_id ),
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);

		return $this->success(
			array(
				'product_id' => (int) $product_id,
				'url'        => get_permalink( $product_id ),
			),
			sprintf( 'Product "%s" created (#%d).', $args['title'], $product_id ),
			array( 'log_id' => $log_id, 'object_type' => 'post', 'object_id' => $product_id )
		);
	}

	/**
	 * woo_product_update
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_product_update( array $args, array $context = array() ) {
		if ( ! $this->ensure_woo() ) {
			return $this->error( 'WooCommerce is not active on this site.' );
		}

		$product_id = absint( $args['product_id'] );
		$product    = wc_get_product( $product_id );
		if ( ! $product ) {
			return $this->error( sprintf( 'Product %d not found.', $product_id ) );
		}

		$state = $this->begin_mutation( $product_id, 'woo_product_update', $args, $context );

		if ( isset( $args['title'] ) ) {
			$product->set_name( sanitize_text_field( $args['title'] ) );
		}
		if ( isset( $args['description'] ) ) {
			$product->set_description( wp_kses_post( $args['description'] ) );
		}
		if ( isset( $args['price'] ) ) {
			$product->set_regular_price( wc_format_decimal( (string) $args['price'] ) );
		}
		if ( isset( $args['sale_price'] ) ) {
			$product->set_sale_price( wc_format_decimal( (string) $args['sale_price'] ) );
		}
		if ( isset( $args['stock'] ) ) {
			$product->set_manage_stock( true );
			$product->set_stock_quantity( absint( $args['stock'] ) );
			$product->set_stock_status( absint( $args['stock'] ) > 0 ? 'instock' : 'outofstock' );
		}
		if ( isset( $args['status'] ) && in_array( $args['status'], array( 'publish', 'draft' ), true ) ) {
			$product->set_status( $args['status'] );
		}

		$product->save();

		return $this->end_mutation(
			$state,
			'post',
			$product_id,
			$this->success(
				array( 'product_id' => $product_id ),
				sprintf( 'Product #%d updated.', $product_id )
			)
		);
	}

	/**
	 * woo_product_list
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_product_list( array $args ) {
		if ( ! $this->ensure_woo() ) {
			return $this->error( 'WooCommerce is not active on this site.' );
		}

		$limit = isset( $args['limit'] ) ? max( 1, min( 50, absint( $args['limit'] ) ) ) : 15;
		$params = array(
			'post_type'      => 'product',
			'post_status'    => array( 'publish', 'draft' ),
			'posts_per_page' => $limit,
		);
		if ( ! empty( $args['search'] ) ) {
			$params['s'] = sanitize_text_field( $args['search'] );
		}

		$q     = new \WP_Query( $params );
		$items = array();
		foreach ( $q->posts as $p ) {
			$wc = wc_get_product( $p->ID );
			$items[] = array(
				'id'     => (int) $p->ID,
				'title'  => $p->post_title,
				'status' => $p->post_status,
				'price'  => $wc ? $wc->get_price() : '',
				'stock'  => $wc ? $wc->get_stock_quantity() : null,
				'url'    => get_permalink( $p->ID ),
			);
		}
		return $this->success( array( 'items' => $items, 'total' => (int) $q->found_posts ), sprintf( 'Listed %d products.', count( $items ) ) );
	}

	/**
	 * woo_report
	 *
	 * @return array
	 */
	public function handle_woo_report() {
		if ( ! $this->ensure_woo() ) {
			return $this->error( 'WooCommerce is not active on this site.' );
		}

		$counts      = wp_count_posts( 'product' );
		$low_stock   = wc_get_products(
			array(
				'stock_status' => 'instock',
				'limit'        => 10,
				'return'       => 'ids',
			)
		);
		$low_stock_items = array();
		foreach ( $low_stock as $pid ) {
			$wc = wc_get_product( $pid );
			if ( $wc && is_numeric( $wc->get_stock_quantity() ) && $wc->get_stock_quantity() <= 5 ) {
				$low_stock_items[] = array(
					'id'    => (int) $pid,
					'title' => $wc->get_name(),
					'stock' => (int) $wc->get_stock_quantity(),
				);
			}
		}

		$report = array(
			'products'         => array(
				'publish' => (int) $counts->publish,
				'draft'   => (int) $counts->draft,
				'private' => (int) $counts->private,
			),
			'low_stock'        => $low_stock_items,
			'currency'         => get_woocommerce_currency(),
			'categories'       => array(),
		);

		foreach ( get_terms( array( 'taxonomy' => 'product_cat', 'hide_empty' => false, 'number' => 15 ) ) as $cat ) {
			if ( is_wp_error( $cat ) ) {
				continue;
			}
			$report['categories'][] = array(
				'name'  => $cat->name,
				'count' => (int) $cat->count,
			);
		}

		return $this->success( $report, sprintf( 'Store report: %d published products.', $report['products']['publish'] ) );
	}
}
