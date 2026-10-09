package net.optifabric.ferrite.mixin;

import com.llamalad7.mixinextras.injector.wrapoperation.Operation;
import com.llamalad7.mixinextras.injector.wrapoperation.WrapOperation;
import net.minecraft.client.renderer.SectionOcclusionGraph;
import net.minecraft.client.renderer.chunk.SectionMesh;
import net.minecraft.core.Direction;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;

@Mixin(SectionOcclusionGraph.class)
public class SectionOcclusionGraphMixin {
	@WrapOperation(
		method = "runUpdates",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/client/renderer/chunk/SectionMesh;facesCanSeeEachother(Lnet/minecraft/core/Direction;Lnet/minecraft/core/Direction;)Z"
		),
		require = 0
	)
	private boolean onFacesCanSeeEachother(
		SectionMesh mesh,
		Direction from,
		Direction to,
		Operation<Boolean> original
	) {
		if (XRayModule.INSTANCE.isEnabled()) {
			return true;
		}
		return original.call(mesh, from, to);
	}
}
