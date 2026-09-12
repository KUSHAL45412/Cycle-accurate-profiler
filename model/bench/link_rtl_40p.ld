/* CV32E40P testbench build: .text at the boot address (0x80). Data sections are
   pinned to fixed addresses matching link_spike_40p.ld so the emitted .text is
   byte-identical between the two builds -- required because branch timing on
   this core depends on instruction alignment. Kept below 1 MB to stay well
   inside the testbench RAM. */
OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0x00000080;
  .text   : { *(.text.init) *(.text .text.*) }
  . = 0x00080000; .rodata : { *(.rodata .rodata.*) *(.srodata .srodata.*) }
  . = 0x00090000; .data   : { *(.data .data.*) *(.sdata .sdata.*) }
  . = 0x000A0000; .bss    : { *(.bss .bss.*) *(.sbss .sbss.*) *(COMMON) }
  _end = .;
  /DISCARD/ : { *(.comment) *(.riscv.attributes) }
}
