package net.optifabric.ferrite.bridge;

import net.minecraft.client.OptionInstance;

public interface OptionInstanceDuck<T> {
	void setUncheckedValue(T newValue);

	@SuppressWarnings("unchecked")
	static <T> OptionInstanceDuck<T> of(OptionInstance<T> option) {
		return (OptionInstanceDuck<T>) (Object) option;
	}
}
