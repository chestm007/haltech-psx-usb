#!/usr/bin/env python3
"""Extract DLLs from ECU Manager MSI with proper 4096-byte sector support."""

import struct
import zlib
import os
import re

def parse_msi_binary_table(msi_path):
    """Parse the Binary table from an MSI file with 4096-byte sectors."""
    with open(msi_path, 'rb') as f:
        data = f.read()
    
    if data[:8] != b'\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1':
        print("Not a CFBF file")
        return []
    
    # Sector size is 2^data[30]
    sector_size_shift = data[30]
    sec_size = 1 << sector_size_shift
    mini_sec_size_shift = data[44]
    mini_sec_size = 1 << mini_sec_size_shift
    
    print(f"Sector size: {sec_size} bytes (shift={sector_size_shift})")
    print(f"Mini sector size: {mini_sec_size} bytes (shift={mini_sec_size_shift})")
    
    start_sector_dir = struct.unpack_from('<I', data, 48)[0]
    start_sector_mini = struct.unpack_from('<I', data, 56)[0]
    
    print(f"Start sector dir: {start_sector_dir}")
    print(f"Start sector mini: {start_sector_mini}")
    
    def get_sector(sector_num):
        offset = sector_num * sec_size
        return data[offset:offset+sec_size]
    
    def get_difat_sectors():
        difat = []
        for i in range(109):
            val = struct.unpack_from('<I', data, i*4)[0]
            if val == 0xFFFFFFFF:
                break
            difat.append(val)
        
        difat_sector = struct.unpack_from('<I', data, 440)[0]
        while difat_sector != 0xFFFFFFFF:
            sec = get_sector(difat_sector)
            for i in range(sec_size // 4):
                val = struct.unpack_from('<I', sec, i*4)[0]
                if val == 0xFFFFFFFF:
                    break
                difat.append(val)
            difat_sector = struct.unpack_from('<I', sec, sec_size-4)[0]
        
        return difat
    
    def get_sector_chain(start_sector, difat):
        sectors = []
        current = start_sector
        visited = set()
        while current != 0xFFFFFFFF and current not in visited:
            visited.add(current)
            if current < len(difat):
                offset = current * sec_size
                sec = data[offset:offset+sec_size]
                sectors.append(sec)
                current = struct.unpack_from('<I', sec, sec_size-4)[0]
            else:
                break
        return b''.join(sectors)
    
    difat = get_difat_sectors()
    print(f"DIFAT entries: {len(difat)}")
    
    dir_chain = get_sector_chain(start_sector_dir, difat)
    print(f"Directory chain size: {len(dir_chain)} bytes")
    
    # Parse directory entries
    entries = {}
    pos = 0
    while pos + 128 <= len(dir_chain):
        entry_data = dir_chain[pos:pos+128]
        
        name_len = struct.unpack_from('<H', entry_data, 64)[0]
        if name_len > 2:
            name = entry_data[0:name_len-2].decode('utf-16le', errors='replace').rstrip('\x00')
        else:
            name = ''
        
        entry_type = entry_data[66]
        start_sector = struct.unpack_from('<I', entry_data, 116)[0]
        size = struct.unpack_from('<I', entry_data, 112)[0]
        
        entries[name] = {
            'type': entry_type,
            'start': start_sector,
            'size': size,
        }
        
        pos += 128
    
    print(f"\nDirectory entries ({len(entries)}):")
    for name, info in sorted(entries.items()):
        if name and info['size'] > 0:
            print(f"  {name}: type={info['type']}, start={info['start']}, size={info['size']}")
    
    # Find the Binary stream
    binary_entry = entries.get('Binary')
    if binary_entry and binary_entry['type'] == 2:
        chain = get_sector_chain(binary_entry['start'], difat)
        binary_data = chain[:binary_entry['size']]
        
        print(f"\nBinary stream found: {len(binary_data)} bytes")
        
        # Parse the Binary table
        # Each entry: Name (null-terminated string) + Compressed data length (4 bytes) + Compressed data
        pos = 0
        results = []
        
        while pos < len(binary_data) - 4:
            name_end = binary_data.find(b'\x00', pos)
            if name_end == -1:
                break
            
            name = binary_data[pos:name_end].decode('ascii', errors='replace')
            pos = name_end + 1
            
            if pos + 4 > len(binary_data):
                break
            
            data_len = struct.unpack_from('<I', binary_data, pos)[0]
            pos += 4
            
            if data_len == 0 or data_len > 100 * 1024 * 1024:
                continue
            
            if pos + data_len > len(binary_data):
                break
            
            compressed = binary_data[pos:pos+data_len]
            pos += data_len
            
            try:
                decompressed = zlib.decompress(compressed, -15)
                results.append((name, decompressed))
                print(f"  {name}: {len(decompressed)} bytes")
            except:
                for wbits in [-18, 15, 31, 47]:
                    try:
                        decompressed = zlib.decompress(compressed, wbits)
                        results.append((name, decompressed))
                        print(f"  {name}: {len(decompressed)} bytes (wbits={wbits})")
                        break
                    except:
                        continue
                else:
                    print(f"  {name}: FAILED to decompress ({len(compressed)} bytes)")
        
        return results
    
    print("\nBinary stream not found in directory entries")
    return []

def main():
    msi_path = './extracted/Haltech ECU Manager - 1.14.0 Release/App/eman_Haltech_1.14.0.msi'
    output_dir = './extracted/msi_extract/binaries'
    
    os.makedirs(output_dir, exist_ok=True)
    
    results = parse_msi_binary_table(msi_path)
    
    if not results:
        print("No results found")
        return
    
    print(f"\nExtracted {len(results)} entries")
    
    # Extract DLLs and EXEs
    for name, data in results:
        if len(data) > 2 and data[:2] == b'MZ':
            e_lfanew = struct.unpack_from('<I', data, 0x3C)[0]
            if e_lfanew + 4 <= len(data) and data[e_lfanew:e_lfanew+4] == b'PE\x00\x00':
                filename = name + '.dll' if 'DLL' in name.upper() else name + '.exe'
                output_path = os.path.join(output_dir, filename)
                trimmed = data.rstrip(b'\x00')
                
                with open(output_path, 'wb') as f:
                    f.write(trimmed)
                
                print(f"Extracted: {filename} ({len(trimmed)} bytes)")

if __name__ == '__main__':
    main()
