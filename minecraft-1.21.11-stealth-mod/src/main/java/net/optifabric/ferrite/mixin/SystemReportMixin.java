package net.optifabric.ferrite.mixin;

import net.minecraft.SystemReport;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(SystemReport.class)
public class SystemReportMixin {
	@Inject(
		method = "toLineSeparatedString()Ljava/lang/String;",
		at = @At("RETURN"),
		cancellable = true,
		require = 0
	)
	private void onToLineSeparatedString(CallbackInfoReturnable<String> cir) {
		String original = cir.getReturnValue();
		if (original == null || (!original.contains("ferritecore.mixins.json") && !original.contains("net.optifabric.ferrite"))) {
			return;
		}
		StringBuilder sanitized = new StringBuilder(original.length());
		for (String line : original.split("\n")) {
			if (line.contains("ferritecore.mixins.json") || line.contains("net.optifabric.ferrite")) {
				continue;
			}
			sanitized.append(line).append('\n');
		}
		cir.setReturnValue(sanitized.toString());
	}
}
