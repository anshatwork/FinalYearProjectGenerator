"""
Minimum Swaps to Arrange a Binary Grid (https://leetcode.com/problems/minimum-swaps-to-arrange-a-binary-grid/)
Algorithm Summary:
This solution works by first counting the number of zeros in each row from right to left.
Then, for each row, it finds the first position where we can place a zero to satisfy the condition.
It swaps the zeros in this position with the ones in the previous positions until all zeros are placed correctly.
The time complexity is O(n^2) and space complexity is O(1).

How to run the Streamlit app:
streamlit run min_swaps.py

How to print the README:
python min_swaps.py --readme
"""

import streamlit as st
import numpy as np
import sys

def minSwaps(grid):
    n = len(grid)
    zeros = [0] * n  # count of zeros in each row from right to left
    for i in range(n):
        count = 0
        j = n - 1
        while j >= 0 and grid[i][j] == 0:
            count += 1
            j -= 1
        zeros[i] = count

    swaps = 0

    for i in range(n):
        needed = n - i - 1
        j = i
        # find the first position where we can place a zero to satisfy the condition
        while j < n and zeros[j] < needed:
            j += 1

        if j == n:  # not enough zeros to place correctly
            return -1

        # swap the zeros in this position with the ones in the previous positions
        while j > i:
            temp = zeros[j]
            zeros[j] = zeros[j - 1]
            zeros[j - 1] = temp
            j -= 1
            swaps += 1

    return swaps


if __name__ == "__main__":
    if "--readme" in sys.argv:
        print(__doc__)
    else:
        st.title("Minimum Swaps to Arrange a Binary Grid")
        grid_size = st.number_input("Enter the size of the grid (n x n):", min_value=1)
        grid_data = np.zeros((grid_size, grid_size), dtype=int)

        # input example data
        for i in range(grid_size):
            for j in range(grid_size):
                grid_data[i][j] = st.number_input(f"Enter value at ({i}, {j}):", min_value=0, max_value=1)

        # visualize the algorithm step-by-step
        st.write("Step 1: Count zeros in each row from right to left")
        st.dataframe(np.array(zeros))

        st.write("Step 2: Find the first position where we can place a zero to satisfy the condition")
        st.progress(j / n)

        st.write("Step 3: Swap the zeros in this position with the ones in the previous positions")
        st.code("swaps += 1")

        # show the final answer
        st.write(f"Minimum swaps needed: {minSwaps(grid_data.tolist())}")