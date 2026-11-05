"""Strict parser for the known SlimeVR UF2 patch workflow; preserves block metadata."""
import struct
from pathlib import Path

class Image:
    def __init__(self, data):
        self.data = bytearray(data)
        self.locations = {}
        if not data or len(data) % 512:
            raise ValueError('UF2 must contain complete 512-byte blocks')
        total = len(data)//512
        numbers = set()
        for offset in range(0, len(data), 512):
            m0,m1,flags,addr,size,num,count,family = struct.unpack_from('<8I',data,offset)
            if (m0,m1) != (0x0a324655,0x9e5d5157) or struct.unpack_from('<I',data,offset+508)[0] != 0x0ab16f30:
                raise ValueError('Invalid UF2 magic')
            if flags != 0x2000 or family != 0x239a00b3 or size != 256:
                raise ValueError('Unexpected flags, family, or payload size')
            if count != total or num >= total or num in numbers:
                raise ValueError('Invalid block numbering')
            numbers.add(num)
            if not 0x1000 <= addr <= 0xea000-size:
                raise ValueError('Unexpected address range')
            for i in range(size):
                if addr+i in self.locations: raise ValueError('Overlapping UF2 payloads')
                self.locations[addr+i] = offset+32+i
    @classmethod
    def load(cls,path): return cls(Path(path).read_bytes())
    def read(self,addr,size):
        try: return bytes(self.data[self.locations[a]] for a in range(addr,addr+size))
        except KeyError as e: raise ValueError('Address missing from UF2') from e
    def write(self,addr,data):
        self.read(addr,len(data))
        for i,value in enumerate(data): self.data[self.locations[addr+i]]=value
    def patch(self,addr,old,new):
        if len(old)!=len(new) or self.read(addr,len(old))!=old:
            raise ValueError(f'Patch precondition failed at {addr:#x}')
        self.write(addr,new)
    def save(self,path): Path(path).write_bytes(self.data)
