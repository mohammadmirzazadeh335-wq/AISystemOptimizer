package net.optifabric.ferrite.mixin;

import java.util.Objects;
import java.util.function.Consumer;
import net.minecraft.client.Minecraft;
import net.minecraft.client.OptionInstance;
import net.optifabric.ferrite.bridge.OptionInstanceDuck;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;

@Mixin(OptionInstance.class)
public class OptionInstanceMixin<T> implements OptionInstanceDuck<T> {
	@Shadow
	T value;

	@Shadow
	@Final
	private Consumer<T> onValueUpdate;

	@Override
	public void setUncheckedValue(T newValue) {
		if (!Minecraft.getInstance().isRunning()) {
			value = newValue;
			return;
		}
		if (!Objects.equals(value, newValue)) {
			value = newValue;
			onValueUpdate.accept(value);
		}
	}
}
