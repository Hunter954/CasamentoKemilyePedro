import random

MESSAGES = [
    'Parabéns, {casal}! Que essa nova fase seja iluminada por amor, parceria e memórias lindas todos os dias.',
    '{casal}, que o casamento de vocês seja o começo de uma vida leve, doce e cheia de cumplicidade. Felicidades!',
    'Desejo ao casal {casal} uma jornada cheia de carinho, risadas, paz e sonhos realizados juntos.',
    '{casal}, que nunca faltem abraços apertados, conversa boa e muito amor no lar de vocês.',
    'Que a história de {casal} seja escrita com ternura, respeito e muitos momentos inesquecíveis. Parabéns!',
    'Felicidades, {casal}! Que cada capítulo dessa união venha com ainda mais amor e alegria.',
]


def generate_loving_message(couple_names='Kemily & Pedro'):
    return random.choice(MESSAGES).format(casal=couple_names)
