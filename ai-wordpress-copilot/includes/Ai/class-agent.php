<?php
/**
 * AI Agent orchestrator: plan → tool calls → results → final answer.
 *
 * @package AIWC
 */

namespace AIWC\Ai;

use AIWC\Chat\Conversation_Store;
use AIWC\Context\Site_Context_Engine;
use AIWC\Log\Activity_Log;
use AIWC\Memory\Memory_Store;
use AIWC\Backup\Snapshot_Manager;
use AIWC\Settings;

defined( 'ABSPATH' ) || exit;

/**
 * Runs the multi-step tool-calling loop against the configured AI API.
 */
class Agent {

	/**
	 * OpenAI-compatible client.
	 *
	 * @var OpenAI_Client
	 */
	private $client;

	/**
	 * Tool registry.
	 *
	 * @var Tool_Registry
	 */
	private $registry;

	/**
	 * Conversation store.
	 *
	 * @var Conversation_Store
	 */
	private $conversations;

	/**
	 * Memory store.
	 *
	 * @var Memory_Store
	 */
	private $memory;

	/**
	 * Site context engine.
	 *
	 * @var Site_Context_Engine
	 */
	private $context;

	/**
	 * Activity log.
	 *
	 * @var Activity_Log
	 */
	private $log;

	/**
	 * Snapshot manager.
	 *
	 * @var Snapshot_Manager
	 */
	private $snapshots;

	/**
	 * Constructor.
	 *
	 * @param OpenAI_Client        $client        API client.
	 * @param Tool_Registry        $registry      Tool registry.
	 * @param Conversation_Store   $conversations Conversations.
	 * @param Memory_Store         $memory        Memory.
	 * @param Site_Context_Engine  $context       Site context.
	 * @param Activity_Log         $log           Activity log.
	 * @param Snapshot_Manager     $snapshots     Snapshots.
	 */
	public function __construct(
		OpenAI_Client $client,
		Tool_Registry $registry,
		Conversation_Store $conversations,
		Memory_Store $memory,
		Site_Context_Engine $context,
		Activity_Log $log,
		Snapshot_Manager $snapshots
	) {
		$this->client        = $client;
		$this->registry      = $registry;
		$this->conversations = $conversations;
		$this->memory        = $memory;
		$this->context       = $context;
		$this->log           = $log;
		$this->snapshots     = $snapshots;
	}

	/**
	 * Run one user command through the agent loop.
	 *
	 * @param int    $conversation_id Conversation id (0 = create new).
	 * @param string $user_message    User command.
	 * @return array{conversation_id: int, message: array, steps: array, usage: array, pending: array, error: string}
	 */
	public function run( $conversation_id, $user_message ) {
		$settings = Settings::all();

		if ( ! Settings::is_configured() ) {
			return array(
				'conversation_id' => 0,
				'message'         => null,
				'steps'           => array(),
				'usage'           => array(),
				'pending'         => array(),
				'error'           => __( 'API connection is not configured. Please set the API key and Base URL in Settings.', 'ai-wordpress-copilot' ),
			);
		}

		$user_message = trim( (string) $user_message );
		if ( '' === $user_message ) {
			return array(
				'conversation_id' => 0,
				'message'         => null,
				'steps'           => array(),
				'usage'           => array(),
				'pending'         => array(),
				'error'           => __( 'Empty message.', 'ai-wordpress-copilot' ),
			);
		}

		if ( empty( $conversation_id ) ) {
			$title          = mb_substr( $user_message, 0, 60 );
			$conversation_id = $this->conversations->create( get_current_user_id(), $title, $settings['model'] );
		} else {
			$conversation = $this->conversations->get( $conversation_id );
			if ( ! $conversation ) {
				return array(
					'conversation_id' => 0,
					'message'         => null,
					'steps'           => array(),
					'usage'           => array(),
					'pending'         => array(),
					'error'           => __( 'Conversation not found.', 'ai-wordpress-copilot' ),
				);
			}
		}

		// Persist the user message.
		$this->conversations->add_message(
			$conversation_id,
			array(
				'role'    => 'user',
				'content' => $user_message,
			)
		);

		$max_steps    = (int) $settings['max_steps'];
		$mode         = (int) $settings['execution_mode'];
		$include_mut  = 1 !== $mode; // Mode 1 exposes read-only tools only.
		$openai_tools = $this->registry->openai_tools( $mode, $include_mut );

		$budget_chars = (int) $settings['context_token_budget'] * 4;
		$history      = $this->conversations->build_context_messages( $conversation_id, $budget_chars );

		$messages = array_merge(
			array( array( 'role' => 'system', 'content' => $this->build_system_prompt( (int) $settings['context_detail'] ) ) ),
			$history
		);

		$steps       = array();
		$pending     = array();
		$total_usage = array(
			'prompt_tokens'     => 0,
			'completion_tokens' => 0,
			'total_tokens'      => 0,
		);

		// Cooperative cancellation: the UI "stop" button sets a timestamped flag.
		// Do NOT clear fresh flags here — a cancel that arrives while this request
		// was still queued must stop this run at its first boundary. Only clear
		// stale flags (older than 30s) left over from crashed runs.
		$cancel_key = 'aiwc_cancel_' . get_current_user_id();
		$flagged_at = (int) get_transient( $cancel_key );
		if ( $flagged_at && ( time() - $flagged_at ) > 30 ) {
			delete_transient( $cancel_key );
		}

		for ( $step = 0; $step < $max_steps; ++$step ) {
			// Cooperative cancellation between steps (UI "stop" button).
			if ( $this->is_cancel_requested( $cancel_key ) ) {
				delete_transient( $cancel_key );
				return $this->finalize_cancelled( $conversation_id, $user_message, $steps, $total_usage, $pending );
			}
			$response = $this->client->chat( $messages, $openai_tools );

			if ( is_wp_error( $response ) ) {
				$error = $response->get_error_message();
				$this->log->log(
					array(
						'command'         => $user_message,
						'tool_name'       => 'api_call',
						'summary'         => 'API call failed',
						'status'          => 'failed',
						'error'           => $error,
						'conversation_id' => $conversation_id,
					)
				);
				return array(
					'conversation_id' => $conversation_id,
					'message'         => null,
					'steps'           => $steps,
					'usage'           => $total_usage,
					'pending'         => $pending,
					'error'           => $error,
				);
			}

			// Accumulate usage.
			if ( isset( $response['usage'] ) && is_array( $response['usage'] ) ) {
				foreach ( array( 'prompt_tokens', 'completion_tokens', 'total_tokens' ) as $key ) {
					$total_usage[ $key ] += isset( $response['usage'][ $key ] ) ? (int) $response['usage'][ $key ] : 0;
				}
			}

			$choice = isset( $response['choices'][0] ) ? $response['choices'][0] : array();
			$assistant = isset( $choice['message'] ) ? $choice['message'] : array();
			$content    = isset( $assistant['content'] ) ? (string) $assistant['content'] : '';
			$tool_calls = isset( $assistant['tool_calls'] ) && is_array( $assistant['tool_calls'] ) ? $assistant['tool_calls'] : array();

			// Persist the assistant turn.
			$assistant_row = array(
				'role'       => 'assistant',
				'content'    => $content,
				'tool_calls' => $tool_calls ? $tool_calls : null,
				'tokens'     => isset( $response['usage']['completion_tokens'] ) ? (int) $response['usage']['completion_tokens'] : 0,
			);
			$this->conversations->add_message( $conversation_id, $assistant_row );

			$messages[] = array(
				'role'       => 'assistant',
				'content'    => $content ? $content : null,
				'tool_calls' => $tool_calls ? $tool_calls : null,
			);

			if ( ! $tool_calls ) {
				// Final answer.
				delete_transient( $cancel_key );
				$this->conversations->update(
					$conversation_id,
					array(
						'add_tokens' => $total_usage['total_tokens'],
						'model'      => isset( $response['model'] ) ? (string) $response['model'] : (string) $settings['model'],
					)
				);
				return array(
					'conversation_id' => $conversation_id,
					'message'         => array(
						'role'    => 'assistant',
						'content' => $content,
					),
					'steps'           => $steps,
					'usage'           => $total_usage,
					'pending'         => $pending,
					'error'           => '',
				);
			}

			// Execute tool calls.
			$executed = 0;
			foreach ( $tool_calls as $call ) {
				// Cooperative cancellation between tool calls as well.
				if ( $this->is_cancel_requested( $cancel_key ) ) {
					delete_transient( $cancel_key );
					return $this->finalize_cancelled( $conversation_id, $user_message, $steps, $total_usage, $pending );
				}
				if ( $executed >= (int) $settings['max_tools_per_request'] ) {
					// Too many calls: tell the model we hit the cap.
					$tool_message = array(
						'role'         => 'tool',
						'tool_call_id' => $call['id'],
						'content'      => wp_json_encode( array( 'success' => false, 'error' => 'Tool call limit reached for this request.' ) ),
					);
					$messages[] = $tool_message;
					$this->conversations->add_message(
						$conversation_id,
						array(
							'role'         => 'tool',
							'content'      => $tool_message['content'],
							'tool_call_id' => $call['id'],
							'tool_name'    => 'limit',
							'status'       => 'error',
						)
					);
					continue;
				}
				++$executed;

				$name = isset( $call['function']['name'] ) ? sanitize_text_field( $call['function']['name'] ) : '';
				$args = array();
				if ( ! empty( $call['function']['arguments'] ) ) {
					$decoded = json_decode( (string) $call['function']['arguments'], true );
					if ( is_array( $decoded ) ) {
						$args = $decoded;
					}
				}

				$tool_meta = $this->registry->get( $name );
				$risk      = $tool_meta ? $tool_meta['risk'] : 'write';
				$is_read   = 'read' === $risk;

				$should_execute = $is_read;
				if ( ! $is_read ) {
					switch ( $mode ) {
						case 1:
							$should_execute = false;
							break;
						case 2:
						case 4:
							$should_execute = false;
							break;
						case 3:
							// Auto: read + write only; destructive/critical need approval.
							$should_execute = in_array( $risk, array( 'read', 'write' ), true );
							break;
					}
					if ( $tool_meta && $tool_meta['needs_confirmation'] ) {
						$should_execute = false;
					}
				}

				if ( $is_read || $should_execute ) {
					$result = $this->registry->execute(
						$name,
						$args,
						array(
							'command'         => $user_message,
							'conversation_id' => $conversation_id,
							'source'          => 'agent',
						)
					);
					$steps[] = array(
						'type'   => 'tool',
						'tool'   => $name,
						'args'   => $args,
						'result' => $this->compact_result( $result ),
						'status' => ! empty( $result['success'] ) ? 'success' : 'failed',
					);
					$tool_content = wp_json_encode( $this->compact_result( $result ) );
					$status       = ! empty( $result['success'] ) ? 'ok' : 'error';
				} else {
					// Create a pending approval; store the tool message id in object_id
					// so approve/reject can update this exact tool result later.
					$approval_id = $this->registry->create_approval(
						$name,
						$args,
						array(
							'command'         => $user_message,
							'conversation_id' => $conversation_id,
						)
					);
					$tool_content = wp_json_encode(
						array(
							'success'     => false,
							'pending'     => true,
							'approval_id' => $approval_id,
							'message'     => 'This operation requires administrator approval. Do not retry; inform the user it is awaiting approval.',
						)
					);
					$status   = 'pending';
					$steps[]  = array(
						'type'       => 'approval',
						'tool'       => $name,
						'args'       => $args,
						'approval_id' => $approval_id,
						'status'     => 'pending',
					);
					$pending[] = array(
						'approval_id' => $approval_id,
						'tool'        => $name,
						'args'        => $args,
					);
				}

				// Persist tool result and remember its message id for later updates.
				$message_id = $this->conversations->add_message(
					$conversation_id,
					array(
						'role'         => 'tool',
						'content'      => $tool_content,
						'tool_call_id' => $call['id'],
						'tool_name'    => $name,
						'status'       => $status,
					)
				);

				if ( 'pending' === $status && ! empty( $approval_id ) ) {
					$this->log->update( $approval_id, array( 'object_id' => $message_id ) );
				}

				$messages[] = array(
					'role'         => 'tool',
					'tool_call_id' => $call['id'],
					'content'      => $tool_content,
				);
			}
		}

		// Step budget exhausted: synthesize a final note.
		delete_transient( $cancel_key );
		$note = __( 'Step limit reached. Partial progress has been recorded; you can continue with a follow-up command.', 'ai-wordpress-copilot' );
		$this->conversations->add_message(
			$conversation_id,
			array(
				'role'    => 'assistant',
				'content' => $note,
			)
		);
		$this->conversations->update( $conversation_id, array( 'add_tokens' => $total_usage['total_tokens'] ) );

		return array(
			'conversation_id' => $conversation_id,
			'message'         => array(
				'role'    => 'assistant',
				'content' => $note,
			),
			'steps'           => $steps,
			'usage'           => $total_usage,
			'pending'         => $pending,
			'error'           => '',
		);
	}

	/**
	 * Check the cancel flag with a direct DB read.
	 *
	 * get_transient() cannot be used here: WordPress caches negative option
	 * lookups ($notoptions) for the whole request, so a flag written by a
	 * concurrent request (the /chat/cancel endpoint) would never be seen while
	 * this long-running request is still alive.
	 *
	 * @param string $cancel_key Transient name.
	 * @return bool
	 */
	private function is_cancel_requested( $cancel_key ) {
		global $wpdb;
		$value = $wpdb->get_var(
			$wpdb->prepare(
				"SELECT option_value FROM {$wpdb->options} WHERE option_name = %s LIMIT 1",
				'_transient_' . $cancel_key
			)
		);
		return null !== $value && '' !== $value;
	}

	/**
	 * Abort the loop gracefully after a cancel request.
	 *
	 * @param int    $conversation_id Conversation id.
	 * @param string $user_message    Original command.
	 * @param array  $steps           Steps so far.
	 * @param array  $total_usage     Usage so far.
	 * @param array  $pending         Pending approvals so far.
	 * @return array
	 */
	private function finalize_cancelled( $conversation_id, $user_message, array $steps, array $total_usage, array $pending ) {
		$note = __( 'Operation cancelled by the administrator. Completed steps are recorded below.', 'ai-wordpress-copilot' );
		$this->conversations->add_message(
			$conversation_id,
			array(
				'role'    => 'assistant',
				'content' => $note,
			)
		);
		$this->conversations->update( $conversation_id, array( 'add_tokens' => $total_usage['total_tokens'] ) );

		$this->log->log(
			array(
				'command'         => $user_message,
				'tool_name'       => 'cancel',
				'summary'         => 'Operation cancelled by admin',
				'status'          => 'rejected',
				'conversation_id' => $conversation_id,
			)
		);

		return array(
			'conversation_id' => $conversation_id,
			'message'         => array(
				'role'    => 'assistant',
				'content' => $note,
			),
			'steps'           => $steps,
			'usage'           => $total_usage,
			'pending'         => $pending,
			'cancelled'       => true,
			'error'           => '',
		);
	}

	/**
	 * Compact a tool result before sending it back to the model.
	 *
	 * @param array $result Full result.
	 * @return array
	 */
	private function compact_result( array $result ) {
		$compact = array(
			'success' => ! empty( $result['success'] ),
			'summary' => isset( $result['summary'] ) ? mb_substr( (string) $result['summary'], 0, 500 ) : '',
		);
		if ( isset( $result['error'] ) ) {
			$compact['error'] = mb_substr( (string) $result['error'], 0, 500 );
		}
		if ( isset( $result['data'] ) ) {
			$json = wp_json_encode( $result['data'] );
			if ( strlen( (string) $json ) > 6000 ) {
				$compact['data'] = json_decode( mb_substr( (string) $json, 0, 6000 ) . '…"', true );
				$compact['data_truncated'] = true;
			} else {
				$compact['data'] = $result['data'];
			}
		}
		if ( ! empty( $result['snapshot_id'] ) ) {
			$compact['snapshot_id'] = (int) $result['snapshot_id'];
		}
		return $compact;
	}

	/**
	 * Build the system prompt.
	 *
	 * @param int $detail Context detail level 1..5.
	 * @return string
	 */
	private function build_system_prompt( $detail ) {
		$mode        = (int) Settings::get( 'execution_mode', 2 );
		$strictness  = (int) Settings::get( 'analysis_strictness', 3 );
		$autonomy    = (int) Settings::get( 'autonomy_level', 2 );
		$mode_labels = array(
			1 => 'ANALYZE-ONLY: never call mutating tools; analyze and suggest only.',
			2 => 'CONFIRM MODE: call read-only tools freely; mutating tools will be queued for administrator approval automatically — always tell the user which operations are awaiting approval.',
			3 => 'AUTO-LOW-RISK: read/write tools run automatically; destructive operations require approval.',
			4 => 'STEP-CONFIRM: every mutating tool call requires individual administrator approval.',
		);

		$lines   = array();
		$lines[] = 'You are "AI WordPress Copilot", a senior WordPress developer, site designer, SEO specialist and content manager acting inside the user\'s WordPress admin panel.';
		$lines[] = 'You can execute REAL operations through tools — not just suggestions. Always prefer acting over describing.';
		$lines[] = '';
		$lines[] = '## Execution policy';
		$lines[] = '- ' . ( isset( $mode_labels[ $mode ] ) ? $mode_labels[ $mode ] : $mode_labels[2] );
		$lines[] = sprintf( '- Analysis strictness: %d/5 — verify facts with read tools before mutating; %s', $strictness, $strictness >= 4 ? 'double-check results and report inconsistencies.' : 'be pragmatic.' );
		$lines[] = sprintf( '- Autonomy level: %d/5 — %s', $autonomy, $autonomy >= 4 ? 'act decisively, propose and execute multi-step plans.' : 'explain your plan briefly before large changes.' );
		$lines[] = '- Never run raw PHP, SQL, shell commands or edit plugin/theme files. Use only the provided tools.';
		$lines[] = '- For destructive operations (delete, mass publish, security settings) always require explicit approval.';
		$lines[] = '- When a tool returns a snapshot_id, mention that the change can be rolled back.';
		$lines[] = '- Work in small verified steps; use list/search tools when ids are unknown — never guess IDs.';
		$lines[] = '';
		$lines[] = '## Output';
		$lines[] = '- Answer in the language the user writes in (Persian or English).';
		$lines[] = '- Use Markdown. Be concise but complete. Report what you did, which tools ran, and what changed.';
		$lines[] = '- End with a short "report of changes" when you modified content.';
		$lines[] = '';
		$lines[] = $this->context->prompt_block( $detail );
		$lines[] = '';
		$memory = $this->memory->prompt_block();
		if ( $memory ) {
			$lines[] = $memory;
		}

		return implode( "\n", $lines );
	}
}
