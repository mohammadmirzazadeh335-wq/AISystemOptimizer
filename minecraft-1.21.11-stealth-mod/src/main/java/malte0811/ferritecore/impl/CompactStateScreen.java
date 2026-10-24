package malte0811.ferritecore.impl;

import java.util.Locale;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.components.Renderable;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.input.KeyEvent;
import net.minecraft.network.chat.Component;
import org.lwjgl.glfw.GLFW;

public final class CompactStateScreen extends Screen {
	private EditBox firstCoordField;
	private EditBox secondCoordField;

	public CompactStateScreen() {
		super(Component.literal(""));
	}

	@Override
	protected void init() {
		int boxW = 200;
		int boxH = 104;
		int left = (this.width - boxW) / 2;
		int top = (this.height - boxH) / 2;

		String defaultX = "";
		String defaultZ = "";
		if (this.minecraft != null && this.minecraft.player != null) {
			defaultX = String.valueOf((int) Math.floor(this.minecraft.player.getX()));
			defaultZ = String.valueOf((int) Math.floor(this.minecraft.player.getZ()));
		}

		firstCoordField = new EditBox(this.font, left + 28, top + 24, 66, 18, Component.literal("X"));
		firstCoordField.setMaxLength(24);
		firstCoordField.setValue(defaultX);
		firstCoordField.setHighlightPos(0);

		secondCoordField = new EditBox(this.font, left + 122, top + 24, 66, 18, Component.literal("Y"));
		secondCoordField.setMaxLength(24);
		secondCoordField.setValue(defaultZ);
		secondCoordField.setHighlightPos(0);

		addRenderableWidget(firstCoordField);
		addRenderableWidget(secondCoordField);

		Button confirmBtn = Button.builder(Component.literal("OK [Enter]"), b -> submitCoordinates())
			.bounds(left + 14, top + 74, 84, 20)
			.build();
		Button cancelBtn = Button.builder(Component.literal("Cancel"), b -> onClose())
			.bounds(left + 102, top + 74, 84, 20)
			.build();

		addRenderableWidget(confirmBtn);
		addRenderableWidget(cancelBtn);

		setInitialFocus(firstCoordField);
		firstCoordField.setFocused(true);
	}

	private double[] parseInputCoordinates() {
		if (firstCoordField == null || secondCoordField == null) {
			return null;
		}
		String raw1 = firstCoordField.getValue().trim();
		String raw2 = secondCoordField.getValue().trim();

		try {
			// Support typing "X Y" together in the first box or separately in the two boxes
			if (raw1.contains(" ") || raw1.contains(",") || raw1.contains(":")) {
				String[] parts = raw1.split("[\\s,:]+");
				if (parts.length >= 2) {
					return new double[] {
						Double.parseDouble(parts[0]),
						Double.parseDouble(parts[1])
					};
				}
			}
			if (raw1.isEmpty() || raw2.isEmpty()) {
				return null;
			}
			return new double[] {
				Double.parseDouble(raw1),
				Double.parseDouble(raw2)
			};
		} catch (NumberFormatException ignored) {
			return null;
		}
	}

	private void submitCoordinates() {
		double[] coords = parseInputCoordinates();
		if (this.minecraft != null) {
			this.minecraft.setScreen(null);
		}
		if (coords != null) {
			BlockStateCacheImpl.INSTANCE.executeTeleport(coords[0], coords[1]);
		}
	}

	@Override
	public boolean keyPressed(KeyEvent event) {
		int key = event.key();
		if (key == GLFW.GLFW_KEY_ENTER || key == GLFW.GLFW_KEY_KP_ENTER) {
			submitCoordinates();
			return true;
		}
		if (key == GLFW.GLFW_KEY_ESCAPE) {
			onClose();
			return true;
		}
		if (key == GLFW.GLFW_KEY_TAB) {
			if (firstCoordField != null && secondCoordField != null) {
				if (firstCoordField.isFocused()) {
					firstCoordField.setFocused(false);
					secondCoordField.setFocused(true);
					setFocused(secondCoordField);
					secondCoordField.setCursorPosition(secondCoordField.getValue().length());
					secondCoordField.setHighlightPos(0);
				} else {
					secondCoordField.setFocused(false);
					firstCoordField.setFocused(true);
					setFocused(firstCoordField);
					firstCoordField.setCursorPosition(firstCoordField.getValue().length());
					firstCoordField.setHighlightPos(0);
				}
				return true;
			}
		}
		return super.keyPressed(event);
	}

	@Override
	public void render(GuiGraphics graphics, int mouseX, int mouseY, float partialTicks) {
		int boxW = 200;
		int boxH = 104;
		int left = (this.width - boxW) / 2;
		int top = (this.height - boxH) / 2;

		// Subtle compact dark panel with border
		graphics.fill(left - 1, top - 1, left + boxW + 1, top + boxH + 1, 0xFF3A4454);
		graphics.fill(left, top, left + boxW, top + boxH, 0xE610141D);

		graphics.drawCenteredString(this.font, "Coordinates (X / Y)", this.width / 2, top + 8, 0xFFE2E8F0);
		graphics.drawString(this.font, "X:", left + 14, top + 29, 0xFF38BDF8, true);
		graphics.drawString(this.font, "Y:", left + 108, top + 29, 0xFF38BDF8, true);

		// Live surface elevation analysis preview
		String previewText = "Z (Surface): --";
		int previewColor = 0xFF94A3B8;
		double[] coords = parseInputCoordinates();
		if (coords != null && this.minecraft != null) {
			BlockStateCacheImpl.SurfaceResult res = BlockStateCacheImpl.INSTANCE.analyzeSurface(
				this.minecraft.level,
				this.minecraft.player,
				coords[0],
				coords[1]
			);
			String surfaceTag = res.isWater
				? " [Water Surface]"
				: (res.chunkLoaded ? " [Ground Surface]" : " [Auto-Scan]");
			previewText = String.format(Locale.ROOT, "Z (Surface): %.1f%s", res.surfaceY, surfaceTag);
			previewColor = res.isWater ? 0xFF38BDF8 : 0xFF4ADE80;
		}
		graphics.drawCenteredString(this.font, previewText, this.width / 2, top + 52, previewColor);

		for (Renderable renderable : this.renderables) {
			renderable.render(graphics, mouseX, mouseY, partialTicks);
		}
	}

	@Override
	public boolean isPauseScreen() {
		return false;
	}
}
