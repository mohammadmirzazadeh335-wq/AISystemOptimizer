package net.optifabric.ferrite.core;

import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.optifabric.ferrite.module.AirPlaceModule;
import net.optifabric.ferrite.module.AutoClickerModule;
import net.optifabric.ferrite.module.FlightModule;
import net.optifabric.ferrite.module.XRayModule;
import org.lwjgl.glfw.GLFW;

/**
 * Zero-log, zero-HUD stealth coordinator for Minecraft 1.21.11 Fabric.
 */
public final class StealthController {
	public static final StealthController INSTANCE = new StealthController();

	private volatile boolean zoomActive = false;

	private StealthController() {}

	public boolean isZoomActive() {
		return zoomActive;
	}

	/**
	 * @return true if the key event should be consumed (cancelled from reaching Vanilla keybinds).
	 */
	public boolean onKeyPress(int key, int action, int modifiers) {
		Minecraft mc = Minecraft.getInstance();
		// Never process hotkeys while any GUI/Chat/Inventory/Sign/Pause screen is open
		if (mc.screen != null || mc.player == null) {
			zoomActive = false;
			return false;
		}

		// Z key: smooth 4x Cave & Ore Zoom while held
		if (key == GLFW.GLFW_KEY_Z) {
			if (action == GLFW.GLFW_PRESS) {
				zoomActive = true;
			} else if (action == GLFW.GLFW_RELEASE) {
				zoomActive = false;
			}
			return false;
		}

		boolean ctrlHeld = (modifiers & GLFW.GLFW_MOD_CONTROL) != 0;
		boolean altHeld = (modifiers & GLFW.GLFW_MOD_ALT) != 0;

		// T key: Toggle 30-50 Variable CPS AutoClicker (consume event so Chat doesn't open mid-PvP)
		if (key == GLFW.GLFW_KEY_T && !ctrlHeld && !altHeld) {
			if (action == GLFW.GLFW_PRESS) {
				AutoClickerModule.INSTANCE.toggle();
			}
			return true;
		}

		// Allow Enter or Ctrl + T to open Chat seamlessly when in-game
		if ((key == GLFW.GLFW_KEY_ENTER || key == GLFW.GLFW_KEY_KP_ENTER || (key == GLFW.GLFW_KEY_T && ctrlHeld))
			&& action == GLFW.GLFW_PRESS) {
			if (mc.options != null && mc.options.keyChat != null) {
				KeyMapping.click(mc.options.keyChat.getDefaultKey());
				return true;
			}
		}

		if (action != GLFW.GLFW_PRESS) {
			return false;
		}

		if (key == GLFW.GLFW_KEY_Y) {
			// Y: Toggle Void, Sky & Mid-Air Block Placement (AirPlace / GodBridge / Sky-Tower)
			AirPlaceModule.INSTANCE.toggle();
			if (AirPlaceModule.INSTANCE.isEnabled() && mc.player != null) {
				AirPlaceModule.INSTANCE.preparePlacementForTick(mc.player, false);
			}
			return true;
		} else if (key == GLFW.GLFW_KEY_X) {
			if (altHeld) {
				// Alt + X: Toggle Mobs + Lava + Water visibility in X-Ray
				XRayModule.INSTANCE.toggleShowMobsAndFluids();
			} else if (ctrlHeld) {
				// Ctrl + X: Toggle Anti-Xray Server Bypass (Exposed-Only Ores)
				XRayModule.INSTANCE.toggleExposedOnlyBypass();
			} else {
				// X: Toggle X-Ray ON / OFF
				XRayModule.INSTANCE.toggle();
			}
			return true;
		} else if (key == GLFW.GLFW_KEY_B) {
			// B: Toggle Mobs + Lava + Water option in X-Ray
			XRayModule.INSTANCE.toggleShowMobsAndFluids();
			return true;
		} else if (key == GLFW.GLFW_KEY_V) {
			if (ctrlHeld) {
				// Ctrl + V: Cycle Flight Anti-Cheat Bypass Mode
				FlightModule.INSTANCE.cycleBypassMode();
			} else {
				// V: Toggle Flight ON / OFF
				FlightModule.INSTANCE.toggle();
			}
			return true;
		}

		return false;
	}

	public void onClientTick(LocalPlayer player) {
		XRayModule.INSTANCE.onTick();
		AutoClickerModule.INSTANCE.onClientTick(player);
		FlightModule.INSTANCE.onTick(player);
	}
}
