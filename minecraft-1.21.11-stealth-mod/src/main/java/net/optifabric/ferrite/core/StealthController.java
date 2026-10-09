package net.optifabric.ferrite.core;

import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
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

	public void onKeyPress(int key, int action, int modifiers) {
		Minecraft mc = Minecraft.getInstance();
		// Never process hotkeys while any GUI/Chat/Inventory/Sign/Pause screen is open
		if (mc.screen != null || mc.player == null) {
			zoomActive = false;
			return;
		}

		// Z key: smooth 4x Cave & Ore Zoom while held
		if (key == GLFW.GLFW_KEY_Z) {
			if (action == GLFW.GLFW_PRESS) {
				zoomActive = true;
			} else if (action == GLFW.GLFW_RELEASE) {
				zoomActive = false;
			}
			return;
		}

		if (action != GLFW.GLFW_PRESS) {
			return;
		}

		boolean ctrlHeld = (modifiers & GLFW.GLFW_MOD_CONTROL) != 0;
		boolean altHeld = (modifiers & GLFW.GLFW_MOD_ALT) != 0;

		if (key == GLFW.GLFW_KEY_X) {
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
		} else if (key == GLFW.GLFW_KEY_B) {
			// B: Toggle Mobs + Lava + Water option in X-Ray
			XRayModule.INSTANCE.toggleShowMobsAndFluids();
		} else if (key == GLFW.GLFW_KEY_V) {
			if (ctrlHeld) {
				// Ctrl + V: Cycle Flight Speed Preset (60 BPS -> 40 BPS -> 80 BPS)
				FlightModule.INSTANCE.cycleBypassMode();
			} else {
				// V: Toggle 60 Blocks/s Lag-Free Flight ON / OFF
				FlightModule.INSTANCE.toggle();
			}
		}
	}

	public void onClientTick(LocalPlayer player) {
		XRayModule.INSTANCE.onTick();
		FlightModule.INSTANCE.onTick(player);
	}
}
