<?php
/**
 * Chat, conversations and approvals REST endpoints.
 *
 * @package AIWC
 */

namespace AIWC\Api;

use AIWC\Security\Permissions;
use AIWC\Settings;

defined( 'ABSPATH' ) || exit;

/**
 * Handles the conversational API.
 */
class Chat_Controller extends Base_Controller {

	/**
	 * Register routes.
	 */
	public function register_routes() {
		register_rest_route(
			Api::NS,
			'/conversations',
			array(
				array(
					'methods'             => \WP_REST_Server::READABLE,
					'callback'            => array( $this, 'list_conversations' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
				array(
					'methods'             => \WP_REST_Server::CREATABLE,
					'callback'            => array( $this, 'create_conversation' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
			)
		);

		register_rest_route(
			Api::NS,
			'/conversations/(?P<id>\d+)',
			array(
				array(
					'methods'             => \WP_REST_Server::READABLE,
					'callback'            => array( $this, 'get_conversation' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
				array(
					'methods'             => \WP_REST_Server::DELETABLE,
					'callback'            => array( $this, 'delete_conversation' ),
					'permission_callback' => array( $this, 'can_manage' ),
				),
			)
		);

		register_rest_route(
			Api::NS,
			'/conversations/(?P<id>\d+)/messages',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'get_messages' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/chat',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'chat' ),
				'permission_callback' => array( $this, 'can_manage' ),
				'args'                => array(
					'message'         => array(
						'type'              => 'string',
						'required'          => true,
						'sanitize_callback' => 'sanitize_textarea_field',
					),
					'conversation_id' => array(
						'type'    => 'integer',
						'default' => 0,
					),
				),
			)
		);

		register_rest_route(
			Api::NS,
			'/chat/cancel',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'cancel_chat' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/approvals',
			array(
				'methods'             => \WP_REST_Server::READABLE,
				'callback'            => array( $this, 'list_approvals' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/approvals/(?P<id>\d+)/approve',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'approve' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);

		register_rest_route(
			Api::NS,
			'/approvals/(?P<id>\d+)/reject',
			array(
				'methods'             => \WP_REST_Server::CREATABLE,
				'callback'            => array( $this, 'reject' ),
				'permission_callback' => array( $this, 'can_manage' ),
			)
		);
	}

	/**
	 * GET /conversations
	 *
	 * @return \WP_REST_Response
	 */
	public function list_conversations() {
		$store = $this->plugin->get( 'conversations' );
		return $this->respond(
			array(
				'items' => $store->list_for_user( get_current_user_id() ),
			)
		);
	}

	/**
	 * POST /conversations
	 *
	 * @return \WP_REST_Response
	 */
	public function create_conversation() {
		$store = $this->plugin->get( 'conversations' );
		$id    = $store->create( get_current_user_id(), __( 'New conversation', 'ai-wordpress-copilot' ), (string) Settings::get( 'model' ) );
		return $this->respond( array( 'id' => $id ), 201 );
	}

	/**
	 * GET /conversations/{id}
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function get_conversation( \WP_REST_Request $request ) {
		$store = $this->plugin->get( 'conversations' );
		$conv  = $store->get( (int) $request['id'] );
		if ( ! $conv ) {
			return $this->error( 'aiwc_not_found', __( 'Conversation not found.', 'ai-wordpress-copilot' ), 404 );
		}
		return $this->respond( $conv );
	}

	/**
	 * DELETE /conversations/{id}
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function delete_conversation( \WP_REST_Request $request ) {
		$store = $this->plugin->get( 'conversations' );
		$conv  = $store->get( (int) $request['id'] );
		if ( ! $conv ) {
			return $this->error( 'aiwc_not_found', __( 'Conversation not found.', 'ai-wordpress-copilot' ), 404 );
		}
		if ( (int) $conv['user_id'] !== get_current_user_id() && ! current_user_can( 'manage_options' ) ) {
			return $this->error( 'aiwc_forbidden', __( 'Not allowed.', 'ai-wordpress-copilot' ), 403 );
		}
		$store->delete( (int) $request['id'] );
		return $this->respond( array( 'deleted' => true ) );
	}

	/**
	 * GET /conversations/{id}/messages
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function get_messages( \WP_REST_Request $request ) {
		$store = $this->plugin->get( 'conversations' );
		$conv  = $store->get( (int) $request['id'] );
		if ( ! $conv ) {
			return $this->error( 'aiwc_not_found', __( 'Conversation not found.', 'ai-wordpress-copilot' ), 404 );
		}
		return $this->respond(
			array(
				'conversation' => $conv,
				'messages'     => $store->get_messages( (int) $request['id'] ),
			)
		);
	}

	/**
	 * POST /chat — run the agent.
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function chat( \WP_REST_Request $request ) {
		if ( ! Settings::is_configured() ) {
			return $this->error(
				'aiwc_not_configured',
				__( 'API connection is not configured. Please configure it in Settings → API Connection.', 'ai-wordpress-copilot' ),
				400
			);
		}

		// Simple per-user rate limit: 15 requests / minute (filterable).
		$rl_key  = 'aiwc_rl_' . get_current_user_id();
		$hits    = (int) get_transient( $rl_key );
		$rl_limit = max( 1, (int) apply_filters( 'aiwc_chat_rate_limit', 15 ) );
		if ( $hits >= $rl_limit ) {
			return $this->error( 'aiwc_rate_limited', __( 'Too many requests. Please wait a moment.', 'ai-wordpress-copilot' ), 429 );
		}
		set_transient( $rl_key, $hits + 1, MINUTE_IN_SECONDS );

		$message = trim( (string) $request['message'] );
		$conv_id = (int) $request['conversation_id'];

		if ( '' === $message ) {
			return $this->error( 'aiwc_empty', __( 'Message is empty.', 'ai-wordpress-copilot' ), 400 );
		}
		if ( strlen( $message ) > 10000 ) {
			return $this->error( 'aiwc_too_long', __( 'Message is too long (max 10000 characters).', 'ai-wordpress-copilot' ), 400 );
		}

		$result = $this->plugin->get( 'agent' )->run( $conv_id, $message );

		if ( ! empty( $result['error'] ) && empty( $result['message'] ) ) {
			return $this->respond(
				array(
					'error'           => $result['error'],
					'conversation_id' => $result['conversation_id'],
					'steps'           => $result['steps'],
				),
				502
			);
		}

		return $this->respond( $result );
	}

	/**
	 * POST /chat/cancel — request cooperative cancellation of the running agent loop.
	 *
	 * @return \WP_REST_Response
	 */
	public function cancel_chat() {
		set_transient( 'aiwc_cancel_' . get_current_user_id(), time(), 5 * MINUTE_IN_SECONDS );
		return $this->respond( array( 'cancelling' => true ) );
	}

	/**
	 * GET /approvals — pending operations.
	 *
	 * @return \WP_REST_Response
	 */
	public function list_approvals() {
		$log = $this->plugin->get( 'log' );
		$res = $log->get_logs(
			array(
				'status'   => 'pending',
				'per_page' => 50,
			)
		);
		$items = array();
		foreach ( $res['items'] as $row ) {
			if ( 'pending' !== $row['approval'] ) {
				continue;
			}
			$items[] = $row;
		}
		return $this->respond( array( 'items' => $items ) );
	}

	/**
	 * POST /approvals/{id}/approve — execute the pending operation.
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function approve( \WP_REST_Request $request ) {
		$log = $this->plugin->get( 'log' );
		$row = $log->get( (int) $request['id'] );
		if ( ! $row || 'pending' !== $row['status'] || 'pending' !== $row['approval'] ) {
			return $this->error( 'aiwc_approval_missing', __( 'Pending operation not found.', 'ai-wordpress-copilot' ), 404 );
		}

		$result = $this->plugin->get( 'registry' )->execute(
			$row['tool_name'],
			is_array( $row['args'] ) ? $row['args'] : array(),
			array(
				'command'         => $row['command'],
				'conversation_id' => $row['conversation_id'],
				'source'          => 'approval',
			)
		);

		$log->update(
			(int) $request['id'],
			array(
				'status'      => ! empty( $result['success'] ) ? 'success' : 'failed',
				'approval'    => 'approved',
				'summary'     => isset( $result['summary'] ) ? $result['summary'] : '',
				'error'       => ! empty( $result['error'] ) ? $result['error'] : '',
				'after_state' => isset( $result['data'] ) ? $result['data'] : null,
			)
		);

		$this->update_tool_message( $row, $result );

		return $this->respond( $result );
	}

	/**
	 * POST /approvals/{id}/reject
	 *
	 * @param \WP_REST_Request $request Request.
	 * @return \WP_REST_Response|\WP_Error
	 */
	public function reject( \WP_REST_Request $request ) {
		$log = $this->plugin->get( 'log' );
		$row = $log->get( (int) $request['id'] );
		if ( ! $row || 'pending' !== $row['status'] ) {
			return $this->error( 'aiwc_approval_missing', __( 'Pending operation not found.', 'ai-wordpress-copilot' ), 404 );
		}

		$log->update(
			(int) $request['id'],
			array(
				'status'   => 'rejected',
				'approval' => 'rejected',
				'summary'  => sprintf( 'Rejected by admin: %s', $row['tool_name'] ),
			)
		);

		$this->update_tool_message(
			$row,
			array(
				'success' => false,
				'rejected' => true,
				'message' => 'The administrator rejected this operation.',
			)
		);

		return $this->respond( array( 'rejected' => true ) );
	}

	/**
	 * Update the stored tool message with the approval outcome so the
	 * conversation transcript stays valid for future turns.
	 *
	 * @param array $row    Log row.
	 * @param array $result Result payload.
	 */
	private function update_tool_message( array $row, array $result ) {
		global $wpdb;
		$message_id = absint( $row['object_id'] );
		if ( ! $message_id ) {
			return;
		}
		$table = \AIWC\Chat\Conversation_Store::messages_table();
		$wpdb->update(
			$table,
			array(
				'content' => wp_json_encode(
					array(
						'success'     => ! empty( $result['success'] ),
						'approved'    => true,
						'summary'     => isset( $result['summary'] ) ? $result['summary'] : '',
						'data'        => isset( $result['data'] ) ? $result['data'] : null,
						'error'       => isset( $result['error'] ) ? $result['error'] : null,
						'rejected'    => ! empty( $result['rejected'] ),
					)
				),
				'status'  => ! empty( $result['success'] ) ? 'ok' : 'error',
			),
			array( 'id' => $message_id )
		);
	}
}
