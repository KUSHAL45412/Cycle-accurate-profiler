#!/usr/bin/env python3
"""
RISC-V Instruction Decoder for CV32E40X
Returns extension tags used by the profiler and predict_engine.

M extension is now split into M:MUL, M:MULH, M:DIV, M:REM sub-tags so
predict_engine can apply the correct latency per the spec:
  mul        → 1 cycle
  mulh/mulhsu/mulhu → 4 cycles
  div/divu/rem/remu → 3-35 cycles (avg ~19)
"""

class RISCVDecoder:

    def __init__(self):
        self.OPCODE_LOAD     = 0x03
        self.OPCODE_STORE    = 0x23
        self.OPCODE_BRANCH   = 0x63
        self.OPCODE_JALR     = 0x67
        self.OPCODE_JAL      = 0x6F
        self.OPCODE_OP_IMM   = 0x13
        self.OPCODE_OP       = 0x33
        self.OPCODE_LUI      = 0x37
        self.OPCODE_AUIPC    = 0x17
        self.OPCODE_SYSTEM   = 0x73
        self.OPCODE_FENCE    = 0x0F
        self.OPCODE_AMO      = 0x2F
        self.OPCODE_LOAD_FP  = 0x07
        self.OPCODE_STORE_FP = 0x27
        self.OPCODE_FMADD    = 0x43
        self.OPCODE_FMSUB    = 0x47
        self.OPCODE_FNMSUB   = 0x4B
        self.OPCODE_FNMADD   = 0x4F
        self.OPCODE_OP_FP    = 0x53

    def decode(self, encoding, is_compressed=False):
        """
        Decode instruction and return extension tag.
        M extension returns sub-tags: 'M:MUL', 'M:MULH', 'M:DIV', 'M:REM'
        I extension returns sub-tags: 'I:ADDI', 'I:LW', 'I:BEQ', etc.
        """
        if is_compressed:
            return self._decode_compressed(encoding)

        opcode = encoding & 0x7F
        funct3 = (encoding >> 12) & 0x7
        funct7 = (encoding >> 25) & 0x7F
        rd     = (encoding >> 7)  & 0x1F
        rs1    = (encoding >> 15) & 0x1F
        rs2    = (encoding >> 20) & 0x1F

        if opcode == self.OPCODE_OP:
            return self._decode_op(funct3, funct7, rs2)
        elif opcode == self.OPCODE_OP_IMM:
            return self._decode_op_imm(funct3, funct7, rs2)
        elif opcode == self.OPCODE_LOAD:
            return {0x0:'I:LB',0x1:'I:LH',0x2:'I:LW',
                    0x4:'I:LBU',0x5:'I:LHU'}.get(funct3, 'I:LOAD')
        elif opcode == self.OPCODE_STORE:
            return {0x0:'I:SB',0x1:'I:SH',0x2:'I:SW'}.get(funct3, 'I:STORE')
        elif opcode == self.OPCODE_BRANCH:
            return {0x0:'I:BEQ',0x1:'I:BNE',0x4:'I:BLT',
                    0x5:'I:BGE',0x6:'I:BLTU',0x7:'I:BGEU'}.get(funct3, 'I:BRANCH')
        elif opcode == self.OPCODE_JAL:  return 'I:JAL'
        elif opcode == self.OPCODE_JALR: return 'I:JALR'
        elif opcode == self.OPCODE_LUI:  return 'I:LUI'
        elif opcode == self.OPCODE_AUIPC:return 'I:AUIPC'
        elif opcode == self.OPCODE_SYSTEM:
            return self._decode_system(funct3, encoding)
        elif opcode == self.OPCODE_FENCE:
            return 'I:FENCE' if funct3 == 0x0 else 'Zifencei'
        elif opcode == self.OPCODE_AMO:
            return 'A'
        elif opcode in [self.OPCODE_LOAD_FP, self.OPCODE_STORE_FP]:
            return 'F' if (funct3 & 0x3) == 0x2 else 'D'
        elif opcode in [self.OPCODE_FMADD, self.OPCODE_FMSUB,
                        self.OPCODE_FNMSUB, self.OPCODE_FNMADD]:
            fmt = (encoding >> 25) & 0x3
            return 'F' if fmt == 0x0 else 'D'
        elif opcode == self.OPCODE_OP_FP:
            return self._decode_fp(encoding)
        return 'I:UNKNOWN'

    def _decode_op(self, funct3, funct7, rs2):
        # M extension — split by sub-type for accurate latency modelling
        # Per CV32E40X spec: mul=1cy, mulh*=4cy, div/rem=3-35cy
        if funct7 == 0x01:
            if funct3 == 0x0: return 'M:MUL'
            if funct3 in [0x1, 0x2, 0x3]: return 'M:MULH'   # mulh, mulhsu, mulhu
            if funct3 in [0x4, 0x5]: return 'M:DIV'          # div, divu
            if funct3 in [0x6, 0x7]: return 'M:REM'          # rem, remu

        # Zba
        if funct7 == 0x10 and funct3 in [0x2, 0x4, 0x6]: return 'Zba'

        # Zbb
        if funct7 == 0x20 and funct3 in [0x1, 0x4, 0x5, 0x6, 0x7]: return 'Zbb'
        if funct7 == 0x30 and funct3 in [0x1, 0x5]: return 'Zbb'

        # Zbc
        if funct7 == 0x05 and funct3 in [0x1, 0x2, 0x3]: return 'Zbc'

        # Zbs
        if funct7 in [0x24, 0x28, 0x2C]: return 'Zbs'

        op_map = {
            0x0: 'I:ADD' if funct7 == 0x00 else 'I:SUB',
            0x1: 'I:SLL', 0x2: 'I:SLT', 0x3: 'I:SLTU',
            0x4: 'I:XOR',
            0x5: 'I:SRL' if funct7 == 0x00 else 'I:SRA',
            0x6: 'I:OR',  0x7: 'I:AND',
        }
        return op_map.get(funct3, 'I:UNKNOWN')

    def _decode_op_imm(self, funct3, funct7, rs2):
        # Zbb immediate forms
        if funct3 == 0x1 and (funct7 >> 1) == 0x30:
            if rs2 in [0x18, 0x19, 0x1C, 0x1D, 0x1E]: return 'Zbb'
        if funct3 == 0x4 and funct7 == 0x34: return 'Zbb'
        if funct3 == 0x5:
            if (funct7 >> 1) == 0x30: return 'Zbb'
            if funct7 == 0x30: return 'Zbb'
        # Zbs immediate forms
        if funct3 in [0x1, 0x5] and funct7 in [0x24, 0x28, 0x2C, 0x34]: return 'Zbs'

        imm_map = {
            0x0:'I:ADDI', 0x1:'I:SLLI', 0x2:'I:SLTI', 0x3:'I:SLTIU',
            0x4:'I:XORI',
            0x5:'I:SRLI' if funct7 == 0x00 else 'I:SRAI',
            0x6:'I:ORI',  0x7:'I:ANDI',
        }
        return imm_map.get(funct3, 'I:UNKNOWN')

    def _decode_system(self, funct3, encoding):
        if funct3 == 0x0:
            imm12 = (encoding >> 20) & 0xFFF
            if imm12 == 0x0: return 'I:ECALL'
            if imm12 == 0x1: return 'I:EBREAK'
            return 'I:SYSTEM'
        return 'Zicsr'

    def _decode_fp(self, encoding):
        fmt = ((encoding >> 25) & 0x7F) >> 2 & 0x3
        return 'D' if fmt == 0x1 else 'F'

    def _decode_compressed(self, encoding):
        """Compressed (16-bit) instruction classification."""
        opc    = encoding & 0x3
        funct3 = (encoding >> 13) & 0x7

        if opc == 0x0:
            if funct3 == 0x2: return 'C:LW'
            if funct3 == 0x6: return 'C:SW'
        if opc == 0x1:
            if funct3 == 0x5: return 'C:J'
            if funct3 == 0x1: return 'C:JAL'
            if funct3 == 0x6: return 'C:BEQZ'
            if funct3 == 0x7: return 'C:BNEZ'
        if opc == 0x2:
            if funct3 == 0x2: return 'C:LWSP'
            if funct3 == 0x6: return 'C:SWSP'
            if funct3 == 0x4:
                rs2 = (encoding >> 2) & 0x1F
                rs1 = (encoding >> 7) & 0x1F
                j12 = (encoding >> 12) & 0x1
                if rs2 == 0 and rs1 != 0:
                    return 'C:JALR' if j12 else 'C:JR'
        return 'C'

    def get_parent_ext(self, tag):
        """Map sub-tags back to parent for area/count tables. M:MUL → M etc."""
        return tag.split(':')[0]


if __name__ == '__main__':
    decoder = RISCVDecoder()
    tests = [
        (0x00000013, False, 'I:ADDI'),
        (0x00A50533, False, 'I:ADD'),
        (0x40A50533, False, 'I:SUB'),
        (0x00002183, False, 'I:LW'),
        (0x00112023, False, 'I:SW'),
        (0x00050063, False, 'I:BEQ'),
        (0x0000006F, False, 'I:JAL'),
        (0x00000067, False, 'I:JALR'),
        (0x000000B7, False, 'I:LUI'),
        (0x00000097, False, 'I:AUIPC'),
        # M sub-types
        (0x02A50533, False, 'M:MUL'),
        (0x02A51533, False, 'M:MULH'),
        (0x02A54533, False, 'M:DIV'),
        (0x02A56533, False, 'M:REM'),
        # Bit manip
        (0x20A50533, False, 'Zba'),
        (0x60A55533, False, 'Zbb'),
        (0x0AA53533, False, 'Zbc'),
        (0x48A51533, False, 'Zbs'),
        (0x00002573, False, 'Zicsr'),
        (0x0000100F, False, 'Zifencei'),
        (0x00000073, False, 'I:ECALL'),
        (0x00100073, False, 'I:EBREAK'),
    ]
    print("Testing RISC-V Decoder:")
    print("=" * 65)
    passed = 0
    for enc, comp, exp in tests:
        got = decoder.decode(enc, comp)
        ok  = got == exp
        passed += ok
        print(f"{'✓' if ok else '✗'} 0x{enc:08x} → {got:<14s}  (expected {exp})")
    print("=" * 65)
    print(f"Passed: {passed}/{len(tests)}")

