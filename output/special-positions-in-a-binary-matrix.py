import streamlit as st
from typing import List, Tuple

# ── Algorithm ───────────────────────────────────────────────────────────────
def solve(mat):
    # Get matrix dimensions
    m = len(mat)
    n = len(mat[0])

    # Initialize row and column counters
    row_counts = [0] * m
    col_counts = [0] * n

    # Create a list to store positions of 1s
    positions = []

    # Iterate over the matrix, counting rows and columns with exactly one 1
    for i in range(m):
        for j in range(n):
            if mat[i][j] == 1:
                row_counts[i] += 1
                col_counts[j] += 1
                positions.append((i, j))

    # Count the number of special positions (where both row and column counts are 1)
    count = 0
    for pos in positions:
        if row_counts[pos[0]] == 1 and col_counts[pos[1]] == 1:
            count += 1

    return count

# ── Streamlit UI ─────────────────────────────────────────────────────────────
def main():
    st.title("Special Positions in a Binary Matrix")
    st.markdown("**Problem:** Count the number of special positions in a binary matrix.")

    # Get user input (matrix dimensions and values)
    m = st.number_input("Matrix rows", min_value=1, max_value=100)
    n = st.number_input("Matrix columns", min_value=1, max_value=100)
    mat_values = [[st.number_input(f"Row {i}, Col {j}", min_value=0, max_value=1) for j in range(n)] for i in range(m)]

    # Validate user input
    if any(not all(0 <= val <= 1 for val in row) for row in mat_values):
        st.error("Please enter binary values (0 or 1).")
        return

    # Create the matrix from user input
    mat = [[val for val in row] for row in mat_values]

    # Visualize the algorithm step-by-step
    st.subheader("Step-by-step")

    # Count rows and columns with exactly one 1
    row_counts = [0] * m
    col_counts = [0] * n
    positions = []
    for i in range(m):
        for j in range(n):
            if mat[i][j] == 1:
                row_counts[i] += 1
                col_counts[j] += 1
                positions.append((i, j))
    st.write("Count rows and columns with exactly one 1:")
    st.dataframe({"Row": [f"Row {i}" for i in range(m)], "Count": row_counts})
    st.dataframe({"Col": [f"Col {j}" for j in range(n)], "Count": col_counts})

    # Count special positions
    count = 0
    for pos in positions:
        if row_counts[pos[0]] == 1 and col_counts[pos[1]] == 1:
            count += 1

    st.write(f"Special positions: {count}")

    # Show the final answer
    answer = solve(mat)
    st.success(f"Answer: {answer}")

if __name__ == "__main__":
    main()