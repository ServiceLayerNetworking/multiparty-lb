import random
from itertools import product

all_topos = list(range(1000))

all_services = [f"svc{i}" for i in range(15)]

all_states = list(product(all_topos, all_services))

random_states = random.sample(all_states, k=25)

print(random_states)

# random_states = [
#     (935, 'svc10'),
#     (124, 'svc14'),
#     (525, 'svc1'),
#     (105, 'svc9'),
#     (170, 'svc2'),
#     (166, 'svc11'),
#     (446, 'svc6'),
#     (279, 'svc6'),
#     (273, 'svc8'),
#     (412, 'svc10'),
#     (214, 'svc1'),
#     (145, 'svc11'),
#     (111, 'svc3'),
#     (775, 'svc0'),
#     (307, 'svc13'),
#     (869, 'svc1'),
#     (878, 'svc8'),
#     (304, 'svc8'),
#     (63, 'svc6'),
#     (464, 'svc1'),
#     (286, 'svc1'),
#     (976, 'svc7'),
#     (811, 'svc9'),
#     (98, 'svc3'),
#     (652, 'svc4')
# ]

new_random_states = [
    (9, 'svc3'),
    (658, 'svc3'),
    (0, 'svc1'),
    (610, 'svc11'),
    (241, 'svc8'),
    (301, 'svc9'),
    (176, 'svc2'),
    (703, 'svc8'),
    (522, 'svc7'),
    (960, 'svc5'),
    (186, 'svc11'),
    (608, 'svc3'),
    (9, 'svc5'),
    (620, 'svc12'),
    (49, 'svc6'),
    (314, 'svc3'),
    (431, 'svc12'),
    (223, 'svc7'),
    (673, 'svc8'),
    (468, 'svc4'),
    (569, 'svc3'),
    (911, 'svc3'),
    (967, 'svc2'),
    (650, 'svc0'),
    (749, 'svc9')
]
