<?php
/**
 * Content management tools: pages, posts, media.
 *
 * @package AIWC
 */

namespace AIWC\Ai\Tools;

use AIWC\Ai\Abstract_Tool_Group;

defined( 'ABSPATH' ) || exit;

/**
 * Create, edit and manage real WordPress content.
 */
class Content_Tools extends Abstract_Tool_Group {

	/**
	 * Declare tools.
	 *
	 * @return array[]
	 */
	public function tools() {
		return array(
			array(
				'name'        => 'create_page',
				'description' => 'Create a new WordPress page with title, content (HTML or blocks), optional parent, template and status. Content may include a professional full-page structure built from sections. If Elementor is active and builder=elementor is requested, content is stored as Elementor data.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'title'       => array( 'type' => 'string', 'description' => 'Page title.' ),
						'content'     => array( 'type' => 'string', 'description' => 'Page content HTML or Gutenberg blocks.' ),
						'status'      => array( 'type' => 'string', 'description' => 'publish, draft or pending. Default draft.', 'enum' => array( 'publish', 'draft', 'pending' ) ),
						'slug'        => array( 'type' => 'string', 'description' => 'Optional URL slug.' ),
						'parent_id'   => array( 'type' => 'integer', 'description' => 'Optional parent page ID.' ),
						'excerpt'     => array( 'type' => 'string', 'description' => 'Optional excerpt.' ),
						'full_width'  => array( 'type' => 'boolean', 'description' => 'Use full-width layout when the theme supports it.' ),
					),
					'required'   => array( 'title', 'content' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_create_page',
			),
			array(
				'name'        => 'update_page',
				'description' => 'Update an existing page or post by ID. Only provided fields are changed. Uses safe merge for content when mode=append or mode=prepend is given.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'post_id'       => array( 'type' => 'integer', 'description' => 'Page/post ID to update.' ),
						'title'         => array( 'type' => 'string', 'description' => 'New title.' ),
						'content'       => array( 'type' => 'string', 'description' => 'New content (replaces existing when content_mode=replace).' ),
						'content_mode'  => array( 'type' => 'string', 'description' => 'replace (default), append or prepend.', 'enum' => array( 'replace', 'append', 'prepend' ) ),
						'excerpt'       => array( 'type' => 'string', 'description' => 'New excerpt.' ),
						'slug'          => array( 'type' => 'string', 'description' => 'New slug.' ),
						'status'        => array( 'type' => 'string', 'description' => 'New status.', 'enum' => array( 'publish', 'draft', 'pending', 'private' ) ),
					),
					'required'   => array( 'post_id' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_update_page',
			),
			array(
				'name'        => 'delete_page',
				'description' => 'Move a page or post to trash (recoverable) or delete it permanently. Permanent deletion requires administrator approval.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'post_id'   => array( 'type' => 'integer', 'description' => 'Page/post ID.' ),
						'permanent' => array( 'type' => 'boolean', 'description' => 'Delete permanently (default false = trash).' ),
					),
					'required'   => array( 'post_id' ),
				),
				'risk'        => 'destructive',
				'handler'     => 'handle_delete_page',
			),
			array(
				'name'        => 'create_post',
				'description' => 'Create a blog post with title, content, categories, tags and status.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'title'       => array( 'type' => 'string', 'description' => 'Post title.' ),
						'content'     => array( 'type' => 'string', 'description' => 'Post content HTML or blocks.' ),
						'excerpt'     => array( 'type' => 'string', 'description' => 'Optional excerpt.' ),
						'status'      => array( 'type' => 'string', 'description' => 'publish, draft or pending. Default draft.', 'enum' => array( 'publish', 'draft', 'pending' ) ),
						'categories'  => array( 'type' => 'array', 'description' => 'Category names (created if missing).' ),
						'tags'        => array( 'type' => 'array', 'description' => 'Tag names.' ),
					),
					'required'   => array( 'title', 'content' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_create_post',
			),
			array(
				'name'        => 'update_post',
				'description' => 'Update an existing blog post by ID: title, content, excerpt, tags, categories, status.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'post_id'      => array( 'type' => 'integer', 'description' => 'Post ID.' ),
						'title'        => array( 'type' => 'string', 'description' => 'New title.' ),
						'content'      => array( 'type' => 'string', 'description' => 'New content.' ),
						'content_mode' => array( 'type' => 'string', 'description' => 'replace (default), append or prepend.', 'enum' => array( 'replace', 'append', 'prepend' ) ),
						'excerpt'      => array( 'type' => 'string', 'description' => 'New excerpt.' ),
						'status'       => array( 'type' => 'string', 'description' => 'New status.', 'enum' => array( 'publish', 'draft', 'pending', 'private' ) ),
						'tags'         => array( 'type' => 'array', 'description' => 'Tag names.' ),
						'categories'   => array( 'type' => 'array', 'description' => 'Category names.' ),
					),
					'required'   => array( 'post_id' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_update_post',
			),
			array(
				'name'        => 'set_content_status',
				'description' => 'Change publication status of a page/post: publish, draft, pending or private.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'post_id' => array( 'type' => 'integer', 'description' => 'Page/post ID.' ),
						'status'  => array( 'type' => 'string', 'description' => 'New status.', 'enum' => array( 'publish', 'draft', 'pending', 'private' ) ),
					),
					'required'   => array( 'post_id', 'status' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_set_status',
			),
			array(
				'name'        => 'media_list',
				'description' => 'List media library items (images and files) with IDs, URLs, alt text and dimensions.',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'limit'  => array( 'type' => 'integer', 'description' => 'Max items, default 15.' ),
						'search' => array( 'type' => 'string', 'description' => 'Search in title/filename.' ),
					),
				),
				'risk'        => 'read',
				'handler'     => 'handle_media_list',
			),
			array(
				'name'        => 'update_media_alt',
				'description' => 'Set the alt text of a media attachment (accessibility + SEO).',
				'parameters'  => array(
					'type'       => 'object',
					'properties' => array(
						'attachment_id' => array( 'type' => 'integer', 'description' => 'Attachment ID.' ),
						'alt_text'      => array( 'type' => 'string', 'description' => 'New alt text.' ),
					),
					'required'   => array( 'attachment_id', 'alt_text' ),
				),
				'risk'        => 'write',
				'handler'     => 'handle_update_media_alt',
			),
		);
	}

	/**
	 * create_page
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_create_page( array $args, array $context = array() ) {
		$title   = sanitize_text_field( $args['title'] );
		$content = wp_kses_post( $args['content'] );
		$status  = in_array( $args['status'] ?? 'draft', array( 'publish', 'draft', 'pending' ), true ) ? $args['status'] : 'draft';

		$postarr = array(
			'post_title'   => $title,
			'post_content' => $content,
			'post_status'  => $status,
			'post_type'    => 'page',
			'post_author'  => get_current_user_id(),
		);
		if ( ! empty( $args['slug'] ) ) {
			$postarr['post_name'] = sanitize_title( $args['slug'] );
		}
		if ( ! empty( $args['parent_id'] ) ) {
			$postarr['post_parent'] = absint( $args['parent_id'] );
		}
		if ( isset( $args['excerpt'] ) ) {
			$postarr['post_excerpt'] = sanitize_textarea_field( $args['excerpt'] );
		}

		$post_id = wp_insert_post( $postarr, true );
		if ( is_wp_error( $post_id ) ) {
			return $this->error( $post_id->get_error_message() );
		}

		if ( ! empty( $args['full_width'] ) ) {
			update_post_meta( $post_id, '_wp_page_template', 'full-width' );
		}

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'create_page',
				'object_type'     => 'post',
				'object_id'       => $post_id,
				'summary'         => sprintf( 'Created page "%s" (#%d)', $title, $post_id ),
				'args'            => $args,
				'after_state'     => $this->plugin->get( 'snapshots' )->capture( 'post', $post_id ),
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);

		return $this->success(
			array(
				'post_id' => (int) $post_id,
				'url'     => get_permalink( $post_id ),
				'status'  => $status,
			),
			sprintf( 'Page "%s" created (#%d).', $title, $post_id ),
			array( 'log_id' => $log_id, 'object_type' => 'post', 'object_id' => $post_id )
		);
	}

	/**
	 * update_page
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_update_page( array $args, array $context = array() ) {
		$post_id = absint( $args['post_id'] );
		$post    = get_post( $post_id );
		if ( ! $post || ! in_array( $post->post_type, array( 'page', 'post', 'product' ), true ) ) {
			return $this->error( sprintf( 'Post %d not found.', $post_id ) );
		}

		$state = $this->begin_mutation( $post_id, 'update_page', $args, $context );

		$postarr = array( 'ID' => $post_id );
		if ( isset( $args['title'] ) ) {
			$postarr['post_title'] = sanitize_text_field( $args['title'] );
		}
		if ( isset( $args['content'] ) ) {
			$mode    = isset( $args['content_mode'] ) ? $args['content_mode'] : 'replace';
			$new     = wp_kses_post( $args['content'] );
			$current = $post->post_content;
			if ( 'append' === $mode ) {
				$postarr['post_content'] = $current . "\n\n" . $new;
			} elseif ( 'prepend' === $mode ) {
				$postarr['post_content'] = $new . "\n\n" . $current;
			} else {
				$postarr['post_content'] = $new;
			}
		}
		if ( isset( $args['excerpt'] ) ) {
			$postarr['post_excerpt'] = sanitize_textarea_field( $args['excerpt'] );
		}
		if ( ! empty( $args['slug'] ) ) {
			$postarr['post_name'] = sanitize_title( $args['slug'] );
		}
		if ( isset( $args['status'] ) && in_array( $args['status'], array( 'publish', 'draft', 'pending', 'private' ), true ) ) {
			$postarr['post_status'] = $args['status'];
		}

		$result = wp_update_post( $postarr, true );
		if ( is_wp_error( $result ) ) {
			return $this->end_mutation( $state, 'post', $post_id, $this->error( $result->get_error_message() ) );
		}

		return $this->end_mutation(
			$state,
			'post',
			$post_id,
			$this->success(
				array(
					'post_id' => $post_id,
					'url'     => get_permalink( $post_id ),
				),
				sprintf( 'Updated "%s" (#%d).', get_the_title( $post_id ), $post_id )
			)
		);
	}

	/**
	 * delete_page
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_delete_page( array $args, array $context = array() ) {
		$post_id   = absint( $args['post_id'] );
		$permanent = ! empty( $args['permanent'] );
		$post      = get_post( $post_id );
		if ( ! $post ) {
			return $this->error( sprintf( 'Post %d not found.', $post_id ) );
		}

		$state = $this->begin_mutation( $post_id, 'delete_page', $args, $context );

		$deleted = $permanent ? wp_delete_post( $post_id, true ) : wp_trash_post( $post_id );
		if ( ! $deleted ) {
			return $this->end_mutation( $state, 'post', $post_id, $this->error( 'Deletion failed.' ) );
		}

		return $this->end_mutation(
			$state,
			'post',
			$post_id,
			$this->success(
				array(
					'post_id'   => $post_id,
					'permanent' => $permanent,
				),
				$permanent
					? sprintf( 'Permanently deleted "%s" (#%d).', $post->post_title, $post_id )
					: sprintf( 'Moved "%s" (#%d) to trash.', $post->post_title, $post_id )
			),
			array( 'deleted' => true )
		);
	}

	/**
	 * create_post
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_create_post( array $args, array $context = array() ) {
		$title   = sanitize_text_field( $args['title'] );
		$content = wp_kses_post( $args['content'] );
		$status  = in_array( $args['status'] ?? 'draft', array( 'publish', 'draft', 'pending' ), true ) ? $args['status'] : 'draft';

		$post_id = wp_insert_post(
			array(
				'post_title'   => $title,
				'post_content' => $content,
				'post_status'  => $status,
				'post_type'    => 'post',
				'post_author'  => get_current_user_id(),
				'post_excerpt' => isset( $args['excerpt'] ) ? sanitize_textarea_field( $args['excerpt'] ) : '',
			),
			true
		);
		if ( is_wp_error( $post_id ) ) {
			return $this->error( $post_id->get_error_message() );
		}

		if ( ! empty( $args['categories'] ) && is_array( $args['categories'] ) ) {
			$ids = array();
			foreach ( $args['categories'] as $cat_name ) {
				$term = term_exists( sanitize_text_field( $cat_name ), 'category' );
				if ( ! $term ) {
					$term = wp_insert_term( sanitize_text_field( $cat_name ), 'category' );
				}
				if ( ! is_wp_error( $term ) ) {
					$ids[] = (int) ( is_array( $term ) ? $term['term_id'] : $term );
				}
			}
			wp_set_post_categories( $post_id, $ids );
		}
		if ( ! empty( $args['tags'] ) && is_array( $args['tags'] ) ) {
			wp_set_post_tags( $post_id, array_map( 'sanitize_text_field', $args['tags'] ) );
		}

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'create_post',
				'object_type'     => 'post',
				'object_id'       => $post_id,
				'summary'         => sprintf( 'Created post "%s" (#%d)', $title, $post_id ),
				'args'            => $args,
				'after_state'     => $this->plugin->get( 'snapshots' )->capture( 'post', $post_id ),
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);

		return $this->success(
			array(
				'post_id' => (int) $post_id,
				'url'     => get_permalink( $post_id ),
				'status'  => $status,
			),
			sprintf( 'Post "%s" created (#%d).', $title, $post_id ),
			array( 'log_id' => $log_id, 'object_type' => 'post', 'object_id' => $post_id )
		);
	}

	/**
	 * update_post
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_update_post( array $args, array $context = array() ) {
		$post_id = absint( $args['post_id'] );
		$post    = get_post( $post_id );
		if ( ! $post || 'post' !== $post->post_type ) {
			return $this->error( sprintf( 'Post %d not found.', $post_id ) );
		}

		$state  = $this->begin_mutation( $post_id, 'update_post', $args, $context );
		$postarr = array( 'ID' => $post_id );

		if ( isset( $args['title'] ) ) {
			$postarr['post_title'] = sanitize_text_field( $args['title'] );
		}
		if ( isset( $args['content'] ) ) {
			$mode = isset( $args['content_mode'] ) ? $args['content_mode'] : 'replace';
			$new  = wp_kses_post( $args['content'] );
			if ( 'append' === $mode ) {
				$postarr['post_content'] = $post->post_content . "\n\n" . $new;
			} elseif ( 'prepend' === $mode ) {
				$postarr['post_content'] = $new . "\n\n" . $post->post_content;
			} else {
				$postarr['post_content'] = $new;
			}
		}
		if ( isset( $args['excerpt'] ) ) {
			$postarr['post_excerpt'] = sanitize_textarea_field( $args['excerpt'] );
		}
		if ( isset( $args['status'] ) && in_array( $args['status'], array( 'publish', 'draft', 'pending', 'private' ), true ) ) {
			$postarr['post_status'] = $args['status'];
		}

		$result = wp_update_post( $postarr, true );
		if ( is_wp_error( $result ) ) {
			return $this->end_mutation( $state, 'post', $post_id, $this->error( $result->get_error_message() ) );
		}

		if ( isset( $args['tags'] ) && is_array( $args['tags'] ) ) {
			wp_set_post_tags( $post_id, array_map( 'sanitize_text_field', $args['tags'] ) );
		}
		if ( isset( $args['categories'] ) && is_array( $args['categories'] ) ) {
			$ids = array();
			foreach ( $args['categories'] as $cat_name ) {
				$term = term_exists( sanitize_text_field( $cat_name ), 'category' );
				if ( ! $term ) {
					$term = wp_insert_term( sanitize_text_field( $cat_name ), 'category' );
				}
				if ( ! is_wp_error( $term ) ) {
					$ids[] = (int) ( is_array( $term ) ? $term['term_id'] : $term );
				}
			}
			wp_set_post_categories( $post_id, $ids );
		}

		return $this->end_mutation(
			$state,
			'post',
			$post_id,
			$this->success(
				array(
					'post_id' => $post_id,
					'url'     => get_permalink( $post_id ),
				),
				sprintf( 'Updated post "%s" (#%d).', get_the_title( $post_id ), $post_id )
			)
		);
	}

	/**
	 * set_content_status
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_set_status( array $args, array $context = array() ) {
		$post_id = absint( $args['post_id'] );
		$status  = $args['status'];
		$post    = get_post( $post_id );
		if ( ! $post ) {
			return $this->error( sprintf( 'Post %d not found.', $post_id ) );
		}

		$state = $this->begin_mutation( $post_id, 'set_content_status', $args, $context );
		$result = wp_update_post( array( 'ID' => $post_id, 'post_status' => $status ), true );
		if ( is_wp_error( $result ) ) {
			return $this->end_mutation( $state, 'post', $post_id, $this->error( $result->get_error_message() ) );
		}

		return $this->end_mutation(
			$state,
			'post',
			$post_id,
			$this->success(
				array( 'post_id' => $post_id, 'status' => $status ),
				sprintf( 'Status of #%d set to %s.', $post_id, $status )
			)
		);
	}

	/**
	 * media_list
	 *
	 * @param array $args Args.
	 * @return array
	 */
	public function handle_media_list( array $args ) {
		$limit  = isset( $args['limit'] ) ? max( 1, min( 50, absint( $args['limit'] ) ) ) : 15;
		$params = array(
			'post_type'      => 'attachment',
			'post_status'    => 'inherit',
			'posts_per_page' => $limit,
			'orderby'        => 'date',
			'order'          => 'DESC',
		);
		if ( ! empty( $args['search'] ) ) {
			$params['s'] = sanitize_text_field( $args['search'] );
		}

		$q     = new \WP_Query( $params );
		$items = array();
		foreach ( $q->posts as $att ) {
			$meta = wp_get_attachment_metadata( $att->ID );
			$items[] = array(
				'id'        => (int) $att->ID,
				'title'     => $att->post_title,
				'filename'  => basename( (string) get_attached_file( $att->ID ) ),
				'url'       => wp_get_attachment_url( $att->ID ),
				'alt'       => (string) get_post_meta( $att->ID, '_wp_attachment_image_alt', true ),
				'mime'      => $att->post_mime_type,
				'width'     => isset( $meta['width'] ) ? (int) $meta['width'] : 0,
				'height'    => isset( $meta['height'] ) ? (int) $meta['height'] : 0,
			);
		}
		return $this->success( array( 'items' => $items ), sprintf( 'Listed %d media items.', count( $items ) ) );
	}

	/**
	 * update_media_alt
	 *
	 * @param array $args    Args.
	 * @param array $context Context.
	 * @return array
	 */
	public function handle_update_media_alt( array $args, array $context = array() ) {
		$attachment_id = absint( $args['attachment_id'] );
		$alt           = sanitize_text_field( $args['alt_text'] );
		if ( 'attachment' !== get_post_type( $attachment_id ) ) {
			return $this->error( sprintf( 'Attachment %d not found.', $attachment_id ) );
		}

		$before = (string) get_post_meta( $attachment_id, '_wp_attachment_image_alt', true );
		update_post_meta( $attachment_id, '_wp_attachment_image_alt', $alt );

		$log_id = $this->plugin->get( 'log' )->log(
			array(
				'command'         => isset( $context['command'] ) ? (string) $context['command'] : '',
				'tool_name'       => 'update_media_alt',
				'object_type'     => 'post',
				'object_id'       => $attachment_id,
				'summary'         => sprintf( 'Updated alt text of attachment #%d', $attachment_id ),
				'args'            => $args,
				'before_state'    => array( 'alt' => $before ),
				'after_state'     => array( 'alt' => $alt ),
				'conversation_id' => isset( $context['conversation_id'] ) ? absint( $context['conversation_id'] ) : 0,
			)
		);

		return $this->success(
			array( 'attachment_id' => $attachment_id, 'alt_text' => $alt ),
			sprintf( 'Alt text of attachment #%d updated.', $attachment_id ),
			array( 'log_id' => $log_id )
		);
	}
}
