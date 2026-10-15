from decimal import Decimal, ROUND_HALF_UP
def z_pdv(x):
    return (Decimal(str(x)) * Decimal('1.2')).quantize(Decimal('0.01'), ROUND_HALF_UP)
