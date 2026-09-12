# config.py
import math

AREA_COST = {
    'I': 100, 'M': 120, 'A': 102, 'F': 40, 'D': 60, 'C': 10,
    'Zba': 25, 'Zbb': 63, 'Zbc': 1, 'Zbs': 38, 'Zicsr': 5, 'Zifencei': 1,
}
TOTAL_AREA = sum(AREA_COST.values())

