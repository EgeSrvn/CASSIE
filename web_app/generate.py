#!/usr/bin/env python3
import argparse
import random
import sys
import time

def parse_size(size_str):
    """Parses a size string (e.g., '10MB', '1GB') into bytes."""
    units = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12}
    size_str = size_str.upper()
    if not size_str[-1].isalpha():
        return int(size_str)
    
    # Handle units with or without 'B' (e.g., '10M' or '10MB')
    unit = ""
    number = ""
    for char in size_str:
        if char.isalpha():
            unit += char
        else:
            number += char
            
    # Normalize 'M' to 'MB' if necessary
    if len(unit) == 1 and unit + "B" in units:
        unit += "B"
        
    if unit in units:
        return int(float(number) * units[unit])
    else:
        raise ValueError(f"Unknown unit: {unit}. Use KB, MB, GB, etc.")

def generate_random_dna(length):
    """Generates a random DNA sequence."""
    return "".join(random.choices("ACGT", k=length))

def generate_random_qual(length):
    """Generates a random quality string (Phred+33)."""
    # specific range for realistic Illumina quality scores
    return "".join(random.choices("!\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJ", k=length))

def create_file(filename, file_format, target_size_bytes, read_len=150):
    """Generates the file content until target size is reached."""
    
    current_size = 0
    read_count = 0
    
    # Buffer for writing to disk efficiently
    buffer_size = 1000  # lines to write at once
    buffer = []

    print(f"Generating {file_format.upper()} file: {filename}")
    print(f"Target size: {target_size_bytes / (1024*1024):.2f} MB")

    with open(filename, 'w') as f:
        while current_size < target_size_bytes:
            read_count += 1
            header_id = f"READ_{read_count}"
            seq = generate_random_dna(read_len)
            
            entry = ""
            if file_format == 'fasta':
                # FASTA format: >Header\nSequence
                entry = f">{header_id}\n{seq}\n"
            
            elif file_format == 'fastq':
                # FASTQ format: @Header\nSequence\n+\nQuality
                qual = generate_random_qual(read_len)
                entry = f"@{header_id}\n{seq}\n+\n{qual}\n"

            buffer.append(entry)
            current_size += len(entry.encode('utf-8'))

            # Write buffer to disk periodically
            if len(buffer) >= buffer_size:
                f.write("".join(buffer))
                buffer = []
                
        # Write remaining buffer
        if buffer:
            f.write("".join(buffer))

    print(f"Done! Final size: {current_size / (1024*1024):.2f} MB")
    print(f"Total reads generated: {read_count}")

def main():
    parser = argparse.ArgumentParser(description="Generate random FASTA or FASTQ files of a specific size.")
    
    parser.add_argument("-o", "--output", required=True, help="Output file path")
    parser.add_argument("-t", "--type", required=True, choices=['fasta', 'fastq'], help="File format: fasta or fastq")
    parser.add_argument("-s", "--size", required=True, help="Approximate target size (e.g., 500KB, 10MB, 1GB)")
    parser.add_argument("-l", "--length", type=int, default=150, help="Read length in bp (default: 150)")

    args = parser.parse_args()

    try:
        target_bytes = parse_size(args.size)
        create_file(args.output, args.type, target_bytes, args.length)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(0)

if __name__ == "__main__":
    main()