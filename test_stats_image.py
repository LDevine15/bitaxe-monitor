#!/usr/bin/env python3
"""Test stats.py output as image."""

import subprocess
import io
import matplotlib.pyplot as plt

def text_to_image(text: str, output_path: str):
    """Convert text to PNG image."""
    import re

    # Remove emojis (they don't render well in monospace)
    text = text.replace('📊', '[Stats]')
    text = text.replace('🏆', '[Best]')
    text = re.sub(r'[^\x00-\x7F]+', '', text)

    # Use monospace font for alignment
    plt.rcParams['font.family'] = 'monospace'
    plt.rcParams['font.size'] = 9

    # Calculate figure size based on text
    lines = text.split('\n')
    max_line_length = max(len(line) for line in lines) if lines else 80
    num_lines = len(lines)

    # Size: ~0.08 inch per character width, 0.15 inch per line height
    fig_width = min(20, max(12, max_line_length * 0.08))
    fig_height = min(30, max(8, num_lines * 0.15))

    print(f"Generating image: {fig_width}x{fig_height} inches, {num_lines} lines")

    fig, ax = plt.subplots(figsize=(fig_width, fig_height))
    fig.patch.set_facecolor('#2B2D31')  # Discord dark background
    ax.set_facecolor('#2B2D31')
    ax.axis('off')

    # Render text
    ax.text(0.02, 0.98, text,
           transform=ax.transAxes,
           fontfamily='monospace',
           fontsize=9,
           color='#DCDDDE',  # Discord text color
           verticalalignment='top',
           horizontalalignment='left')

    # Save
    plt.savefig(output_path, format='png', dpi=150, bbox_inches='tight',
               facecolor='#2B2D31', edgecolor='none')
    plt.close(fig)


def main():
    print("Running stats.py stats...")
    result = subprocess.run(
        ['python', 'stats.py', 'stats'],
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return 1

    stats_output = result.stdout
    print(f"Got {len(stats_output)} characters, {len(stats_output.split(chr(10)))} lines")

    print("Converting to image...")
    text_to_image(stats_output, 'test_stats.png')

    print("✅ Image saved to test_stats.png")
    return 0


if __name__ == "__main__":
    exit(main())
