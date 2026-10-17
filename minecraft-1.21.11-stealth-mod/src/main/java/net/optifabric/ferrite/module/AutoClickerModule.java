package net.optifabric.ferrite.module;

import java.util.concurrent.ThreadLocalRandom;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.HitResult;
import net.optifabric.ferrite.bridge.MinecraftAccessor;

/**
 * Ultra-Stealth Variable 30-50 CPS AutoClicker (Toggled via 'T' key).
 *
 * Engineered specifically to bypass Vulcan, Matrix, Grim, and Karhu AutoClicker
 * statistical checks (Standard Deviation, Kurtosis, Skewness, Shannon Entropy,
 * Duplicate Interval, and Packet-Tick Correlation) on play.trexmine.com,
 * Phoenix.GameUP.IR, and smp3.mcsh.io.
 */
public final class AutoClickerModule {
	public static final AutoClickerModule INSTANCE = new AutoClickerModule();

	public static final double MIN_CPS = 30.0;
	public static final double MAX_CPS = 50.0;

	private volatile boolean enabled = false;

	/**
	 * Dynamically drifting CPS target between 30.0 and 50.0 CPS.
	 * Uses an Ornstein-Uhlenbeck random walk + dual-frequency wave so CPS
	 * never stays flat and varies organically across every second.
	 */
	private double currentTargetCps = 39.5;
	private double cpsVelocity = 0.0;
	private long nextClickNano = 0L;
	private long lastDriftUpdateNano = 0L;
	private int clickPhase = 0;

	private AutoClickerModule() {}

	public boolean isEnabled() {
		return enabled;
	}

	public void toggle() {
		setEnabled(!enabled);
	}

	public void setEnabled(boolean state) {
		if (this.enabled == state) {
			return;
		}
		this.enabled = state;
		long now = System.nanoTime();
		this.nextClickNano = now;
		this.lastDriftUpdateNano = now;
		this.currentTargetCps = ThreadLocalRandom.current().nextDouble(34.0, 46.0);
		this.cpsVelocity = 0.0;
		this.clickPhase = 0;
	}

	/**
	 * Called at the start of every rendered frame in Minecraft.runTick(boolean).
	 * Executes clicks on the main client thread at exact nanosecond-scheduled
	 * intervals corresponding to 30..50 variable CPS.
	 */
	public void onRenderFrame(Minecraft mc) {
		if (!enabled || mc == null) {
			return;
		}

		LocalPlayer player = mc.player;
		if (player == null || mc.level == null || mc.gameMode == null) {
			return;
		}

		// Pause automatically when any GUI (Inventory, Chest, Shop, Chat, Pause Menu) is open
		if (mc.screen != null || mc.getOverlay() != null) {
			nextClickNano = System.nanoTime() + 25_000_000L;
			return;
		}

		// Pause while eating food / drinking potions / drawing bow so we never trigger
		// Vulcan/Grim "AutoClicker while using item" or interrupt Golden Apple eating
		if (player.isUsingItem()) {
			nextClickNano = System.nanoTime() + 25_000_000L;
			return;
		}

		// If the player is actively breaking a solid block (e.g. Bed in BedWars or Ore)
		// while holding Left Click, let Vanilla's continueAttack finish breaking it
		// instead of resetting block damage progress.
		if (mc.hitResult != null
			&& mc.hitResult.getType() == HitResult.Type.BLOCK
			&& mc.options.keyAttack.isDown()
			&& mc.gameMode.isDestroying()) {
			nextClickNano = System.nanoTime() + 25_000_000L;
			return;
		}

		long now = System.nanoTime();
		if (now < nextClickNano) {
			return;
		}

		// If more than 120ms elapsed (e.g. lag spike or menu just closed), reset schedule
		if (now - nextClickNano > 120_000_000L) {
			nextClickNano = now;
		}

		// Allow up to 2 clicks per frame if frame time > 25ms so 30-50 CPS is maintained
		// even if FPS temporarily dips to 30-45 FPS.
		int clicksThisFrame = 0;
		while (now >= nextClickNano && clicksThisFrame < 2) {
			performSingleClick(mc, player);
			long intervalNanos = computeNextHumanizedIntervalNanos(now);
			nextClickNano += intervalNanos;
			if (nextClickNano < now - 35_000_000L) {
				nextClickNano = now + intervalNanos;
			}
			clicksThisFrame++;
		}
	}

	private void performSingleClick(Minecraft mc, LocalPlayer player) {
		if (!(mc instanceof MinecraftAccessor accessor)) {
			return;
		}

		// Clear Vanilla 10-tick miss cooldown so every click registers immediately
		accessor.ferrite$setMissTime(0);

		HitResult hit = mc.hitResult;
		if (hit != null && hit.getType() == HitResult.Type.BLOCK) {
			BlockHitResult blockHit = (BlockHitResult) hit;
			// When aiming at a block without holding Left Click to mine, swing hand
			// and click without resetting ongoing block destruction
			if (!mc.gameMode.isDestroying()) {
				accessor.ferrite$invokeStartAttack();
			} else {
				player.swing(InteractionHand.MAIN_HAND);
			}
			return;
		}

		// Invoke Vanilla's real startAttack() method:
		// - Attacks entity if crosshair is on an EntityHitResult
		// - Swings MAIN_HAND and sends ServerboundInteractPacket / ServerboundSwingPacket
		// - Registers in all CPS counters
		accessor.ferrite$invokeStartAttack();
	}

	/**
	 * Generates the next inter-click delay in nanoseconds for a variable 30 to 50 CPS
	 * distribution with realistic Bimodal Butterfly / Drag-Click statistics:
	 * - Mean CPS wanders smoothly between 30.0 and 50.0 CPS (20.0ms to 33.33ms).
	 * - Bimodal double-click pairing (fast switch bounce + slightly longer finger reset)
	 *   produces non-zero skewness and positive kurtosis (> 0.5) to defeat Vulcan,
	 *   Matrix, Grim, and Karhu statistical analysis checks.
	 */
	private long computeNextHumanizedIntervalNanos(long now) {
		ThreadLocalRandom rng = ThreadLocalRandom.current();
		clickPhase++;

		// Update wandering CPS target every ~60ms using Ornstein-Uhlenbeck drift
		double dtSeconds = Math.min(0.1, (now - lastDriftUpdateNano) * 1.0E-9);
		if (dtSeconds >= 0.045) {
			lastDriftUpdateNano = now;
			double meanCps = 40.0 + 6.5 * Math.sin(now * 1.7E-9) + 3.0 * Math.cos(now * 4.3E-9);
			double pullToMean = (meanCps - currentTargetCps) * 3.2 * dtSeconds;
			double randomShock = rng.nextGaussian() * 4.8 * Math.sqrt(dtSeconds);
			cpsVelocity = cpsVelocity * 0.72 + pullToMean + randomShock;
			currentTargetCps = Math.clamp(currentTargetCps + cpsVelocity, MIN_CPS + 1.5, MAX_CPS - 1.5);
		}

		// Instantaneous CPS for this click with bimodal butterfly/drag double-click asymmetry
		double instantCps = currentTargetCps;
		if ((clickPhase & 1) == 0) {
			// Double-click bounce pulse (faster half of butterfly pair)
			instantCps += Math.abs(rng.nextGaussian()) * 3.8 + 1.6;
		} else {
			// Finger recovery pulse (slower half of butterfly pair -> positive skewness)
			instantCps -= Math.abs(rng.nextGaussian()) * 3.6 + 1.4;
		}

		// Occasional human micro-outlier every ~17 clicks (defeats Kurtosis / Outlier checks)
		if (clickPhase % 17 == 0) {
			instantCps += rng.nextDouble(-5.5, 5.5);
		}

		// Strictly clamp within the user's requested [30.0, 50.0] CPS bounds
		instantCps = Math.clamp(instantCps, MIN_CPS, MAX_CPS);

		double baseNanos = 1_000_000_000.0 / instantCps;
		// Add sub-millisecond hardware polling jitter so two intervals are never bit-identical
		long jitterNanos = rng.nextLong(-450_000L, 450_000L);
		long finalNanos = Math.round(baseNanos) + jitterNanos;

		// Hard safety bounds: 20.0ms (50 CPS) to 33.33ms (30 CPS)
		return Math.clamp(finalNanos, 20_000_000L, 33_333_333L);
	}
}
