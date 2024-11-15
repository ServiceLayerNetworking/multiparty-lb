from gurobipy import Model, GRB

# Initialize weights
weights = [1, 1, 1]  # example weights for x1, x2, x3

# Create a new model
model = Model("weighted_max_min_with_x1_constraint")

# Define variables x1, x2, x3 (with lower bounds of 0 for simplicity)
x1 = model.addVar(lb=-GRB.INFINITY, ub=1.55, name="x1")
x2 = model.addVar(lb=0, ub=15, name="x2")
x3 = model.addVar(lb=0, ub=15, name="x3")

# Define an auxiliary variable to represent the minimum weighted value
min_x_weighted = model.addVar(name="min_x_weighted")

# Add constraints to enforce min_x_weighted <= x_i / w_i for each variable
model.addConstr(min_x_weighted <= x1 / weights[0], "weighted_min_constraint_1")
model.addConstr(min_x_weighted <= x2 / weights[1], "weighted_min_constraint_2")
model.addConstr(min_x_weighted <= x3 / weights[2], "weighted_min_constraint_3")

model.addConstr(x1 + x2 + x3 == 15, "constraint_sum")

# Set the objective to maximize min_x_weighted
model.setObjective(min_x_weighted, GRB.MAXIMIZE)

# Optimize the model
model.optimize()

# Output the results
if model.status == GRB.OPTIMAL:
    print(f"Optimal value of x1: {x1.X}")
    print(f"Optimal value of x2: {x2.X}")
    print(f"Optimal value of x3: {x3.X}")
    print(f"Maximum of minimum weighted value (min_x_weighted): {min_x_weighted.X}")
else:
    print("No optimal solution found.")