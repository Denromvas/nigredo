lines = [l for l in open('../../дані/текст.txt', encoding='utf-8').read().split('\n') if l]
print(f'рядків: {len(lines)}')
