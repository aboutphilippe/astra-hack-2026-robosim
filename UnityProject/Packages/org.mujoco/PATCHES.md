# Local compatibility patch

## MuJoCo 3.12.0 VFS ABI layout

`Runtime/Bindings/MjBindings.cs` declares the generated `_mjVFS` struct as empty in the upstream 3.12.0 release. The matching native header `include/mujoco/mjmodel.h` defines `mjVFS` with one `void* impl_` field. This package adds that single field to the managed struct, leaving the native binary and all other upstream source unchanged.

The existing `MjVfs` constructor allocates `Marshal.SizeOf(_managedVfs)` bytes before passing the allocation to `mj_defaultVFS`. The empty managed struct therefore allocates too little memory. Using the pointer field makes the managed allocation match the native ABI.

Validation used the Mono compiler/runtime bundled with Unity 6000.3.10f1 to compile the package bindings and print `Marshal.SizeOf(typeof(Mujoco.MujocoLib._mjVFS))`. Upstream result: **1 byte**. Patched result: **8 bytes**. `IntPtr.Size` is also **8 bytes**, matching the native one-pointer structure on macOS arm64 and x86_64.

Upstream source: https://github.com/google-deepmind/mujoco/blob/3.12.0/include/mujoco/mjmodel.h

This change is project-local and does not modify the signed MuJoCo library.
