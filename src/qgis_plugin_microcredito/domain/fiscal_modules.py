"""Official fiscal-module sizes and territorial assessment.

The municipal values are the republished Annex IV of INCRA Special Instruction
no. 6/2025.  Each packed record stores `IBGE code * 256 + hectares` as an
unsigned big-endian integer.
"""

from __future__ import annotations

import base64
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from typing import Final

SOURCE_RULE: Final = (
    "Instrução Especial INCRA nº 5/2022, Anexo IV, "
    "republicado pela Instrução Especial INCRA nº 6/2025"
)
SOURCE_URL: Final = (
    "https://www.in.gov.br/web/dou/-/instrucao-especial-incra-n-6-"
    "de-4-de-julho-de-2025-640263739"
)
LEGAL_REFERENCE: Final = "Lei nº 11.326/2006, art. 3º"
SOURCE_DATE: Final = "2025-07-08"
EXPECTED_MUNICIPALITIES: Final = 5_571

_PACKED_MODULES = (
    "EMjvPBDI9zwQyP88EMkRPBDJGDwQySA8EMkoPBDJMDwQyUI8EMlKPBDJUjwQyVo8EMliPBDJdDwQyXs8EMmdPBDJ"
    "rTwQyd48EMnmPBDKADwQygg8EMoQPBDKIDwQyjI8EMo6PBDKWzwQynM8EMqkPBDK1jwQyzk8EMucPBDMCTwQzGw8"
    "EMx8PBDMjDwQzM08EM0wPBDNkzwQzfY8EM5ZPBDOezwQzoo8EM6cPBDOpDwQzqw8EM60PBDOvDwQzvc8EM8pPBDP"
    "jDwQz708EM/vPBJPjWQST7ZkEk/oZBJQCkYSUDNGElBLZBJQfGQSUK5kElDIZBJQ0GQSUNhkElDfZBJRAWQSUQlk"
    "ElERRhJRK2QSUTNkElFCZBJRdGQSUeFkElJEZBJSp0YT1j1kE9ZcZBPWdmQT1oZkE9awZBPW6WQT10xQE9e5ZBPY"
    "HFAT2H9kE9iXUBPYyFAT2OJkE9lFZBPZZ1AT2ahkE9oJZBPabFAT2qdQE9rZZBPbPGQT259kE9wCZBPcZWQT3JZk"
    "E9zIZBPdK2QT3VxQE92OUBPdv2QT3flQE95cZBPev2QT3yJkE9+FZBPf6FAT4BlQE+BLChPgrmQT4RFkE+F0UBPh"
    "31AT4kJQE+KlZBPjCGQT42tQE+POZBPj8FAT5BFQE+QxZBPklGQT5QFkE+VkZBPllVAT5cVQE+X+ZBPmKGQT5otk"
    "E+atZBPmxGQT5u5QE+dRUBVc21AVXPJQFV0kUBVdX1AVXW9QFV2RZBVdqWQVXdpkFV30ZBVeV1AVXohQFV6YZBVe"
    "umQVXx1kFV+AUBbjy0YW4+NGFuQuMhbkkUYW5LtGFuT0SxblV0YW5bpLFuYdRhbmgAcW5rtGFubtNxbnHjcW505L"
    "FuexRhboFEYW6EVLFuh3Rhbo2gUW6QtLFuk9BxbpiEYW6aA3FuoNNxbqHUsW6j5GFupWRhbqcEYW6tM3FusESxbr"
    "NEEW65dGFuvIRhbr+jcW7F03FuzANxbtLUEW7ZA3Fu3zSxbuJDcW7ixLFu40RhbuVkYW7odLFu65Nxbu2zcW7upG"
    "Fu8aSxbvREsW72U3Fu91NxbvfUYW7+A3FvBNRhbwsDcW8OE3FvETNxbxdksW8dlGFvIKSxbyPEYW8p9LFvMARhbz"
    "OzcW8203FvPQRhb0MzcW9JY3FvSmBxb0x0YW9PlGFvVcRhb1v0YW9fBLFvYiSxb2hUEW9rZLFvbQRhb27zcW9wdL"
    "FvcoRhb3UksW97VGFvgYSxb4ezcW+J1LFvjORhb41kYW+N43FvkARhb5D0sW+UE3FvljSxb5cksW+aRBFvoRRhb6"
    "dEYW+tVGFvs4Nxb7QDcW+1pLFvtxSxb7izcW+5NLFvubNxb7/kEW/C8HFvxhQRb8xDcW/P9LFv0XSxb9MTcW/ZRL"
    "Fv33Sxb+WjcW/rs3Fv8eNxb/T0YW/4E3Fv/kSxcAUTcXAIJLFwCKNxcAkjcXALRGFwEXNxcBekYXAatLFwHdRhcC"
    "QEEXAnEyFwJ5NxcCi0sXAqEyFwLDNxcC0ksXAvRLFwMERhcDHjcXAz9GFwNxNxcD1EsXBAVLFwQ3SxhqNzIYamlG"
    "GGqaMhhqzEYYatQyGGruMhhq/TIYaxdGGGsvMhhrkkYYa/VGGGwXMhhsJkYYbFgyGGzFRhhtKEYZ8ZtQGfHNUBnx"
    "/lAZ8jBQGfNjUBn0ilAZ9LtQGfTtUBn1vVAZ+A9QGfhwRhn43VAZ+Q5QGflAUBn5o1AZ+gZQGfqaUBn7L1AZ+/VQ"
    "GfxgUBn8kVAZ/KFQGfzDUBn9JlAZ/YlQGf6yUBn/FVAZ/3hQGf+SUBn/olAZ/7tQGf/LUBn/01AZ/+VQGgCpUBoC"
    "mFAaBI5QGgYkUBoGVVAaBodQGggRUBoIdFAaCRJQGgoKUBoMAVAaDGRQGgzHUBoNKlAaDY1QGg4hUBoOhFAaDrZQ"
    "GhCtUBoQ3lAaERBQGhPNUBoU9lAaFbxQGhbvUBoZrFAaGnJQGhs4UBob/FAaHZJQGh67UBofHlAaH09QGh+JUBog"
    "HVAaIRVQGiFGUBoheFAaIj5QGiKhUBokNVAaJJhQGiXBUBomJFAaJpFQGiclUBooG1AaKH5QGirAUBorOlAaK51Q"
    "GivOUBosO1AaLTNQGi35UBouKlAaL41QGi/wUBowU1AaMRlQGjF8UBoxrVAaMd9QGjMQUBoz1lAaNP9QGjYoUBo2"
    "lVAaNvZQGje8UBo4H1AaOIJQGjizUBo45VAaORZQGjmDUBo5tVAaOeZQGjoYUBo6OEYaOlFQGjphUBo6c1AaOntQ"
    "GjrcUBo+wlAaPyVQGj9WUBo/iFAaP8NQGj/1UBpAs1AaQU9QGkHkUBpCFVAaQkdQGkJpUBpCklAaQqhQGkMVUBpD"
    "eFAaQ6lQGkPbUBpG4VAaRvtQIAtXSyALiUYgC7pGIAvsNyAMTzcgDLI8IAzURiAM/TwgDRVLIA1GSyANeEsgDeU3"
    "IA5IRiAOYDcgDok8IA6rRiAO3EYgDww3IA9vRiAP0jwgEAMeIBA1NyAQZjcgEJhLIBEFRiARaEYgEctGIBHjRiAS"
    "DDwgEi5LIBKRNyASszwgEtJLIBLyPCATFDwgEz08IBNVRiAThjwgE7hGIBQlRiAUNTwgFFZLIBRmRiAUiDcgFOs3"
    "IBUcSyAVTksgFbE3IBXiPCAWFEsgFndLIBbYNyAXRTcgF1U3IBd2SyAXhksgF6hGIBfZSyAYCzwgGG5GIBjRRiAZ"
    "AjwgGTRGIBmXNyAZyEsgGfpGIBpdRiAayDIgGvlLIBsJSyAbEUYgGyNGIBsrSyAbjkYgG/FLIBxURiAct0YgHOhL"
    "IB0aRiAdNEYgHUs8IB1lSyAdfUYgHeBGIB5NNyAerUYgHxBBIB9BPCAfczwgH9ZLICAHRiAgOTcgIFNLICBqRiAg"
    "hEYgIJxLICEJMiAhOksgIWw8ICHPPCAiMjwgIkJGICJcPCAiazwgIoVLICKTPCAi9ksgI1lLICO8RiAj1ksgI/c8"
    "ICQHSyAkKUYgJIw3ICTvNyAlBzcgJTBGICVSRiAlgzcgJbU3ICYYPCAmeUsgJtxGICdJRiAneksgJ6xGICfdSyAo"
    "DzwgKEA3IChyHiAo1TcgKThGICmbNyAp/kYgKmlGICqaRiAqzDwgKy88ICtgNyArkjcgK/U3ICwmRiAsWDwgLLs3"
    "IC0ePCAtgTcgLeQ8IC5PSyAugDcgLrJGIC8VRiAvN0sgL1Y3IC94RiAv20YgMAweIDA+SyAwb0sgMKEeIDEESyAx"
    "P0YgMXE8IDHUPCAyNTwgMldLIDKYRiAy+zcgMx1GIDNGRiAzXjwgM8FGIDQkNyA0kUYgNMJLIDT0RiA1V0sgNYhL"
    "IDW6RiA2GzcgNjU8IDZMSyA2ZjcgNn5GIDbhHiA3EkYgN0QPIDexPCA4FDcgOCxLIDhVSyA4d0sgOI8yIDi4MiA4"
    "2jcgOOo8IDkERiA5E0sgOS03IDk9RiA5oEYgOdFGIDoBSyA6ZEYgOtE3IDrpPCA7EjwgOzRGIDuXSyA7yEsgO/pG"
    "IDxdRiA8wEYgPSM3ID1USyA9hjwgPfE8IEHXPCGR9UYhkidGIZKKRiGSu0YhktVGIZLtNyGTUB4hk4tGIZO9RiGU"
    "IEYhlINGIZTmRiGVSUYhlXpGIZWqRiGV2zwhlg1LIZY+SyGWWEYhlnA8IZbdSyGXQEYhl6M8IZfURiGX5EYhmAYe"
    "IZhpRiGYi0YhmKo8IZjMRiGZL0YhmT83IZlJRiGZWTchmWg8IZmERiGZkDchmao8IZnLPCGZ20YhmeM3IZnrRiGZ"
    "/UYhmgVGIZoVRiGaPjchmmA3IZqLRiGaw0YhmyY8IZtXRiGbiUYhm6s3IZu6RiGb7DwhnB03IZxPPCGcVzchnGk8"
    "IZxxHiGcgEYhnJpGIZyyRiGc40YhnRVLIZ2ASyGd40YhnkZLIZ5eRiGedx4hnodGIZ6pHiGe2kYhnwxGIZ8cPCGf"
    "PUYhn29GIZ/SRiGgNTchoGZGIaCYRiGg00YhoQVGIaFmRiGhyUYhofpGIaIsRiGij0YhosBGIaLySyGjVUYho4ZG"
    "IaO4RiGj8zchpCVGIaSIRiGk60YhpUtGIaWuRiGl30YhphFGIaZCRiGmXDchpnRGIaavRiGm4TchpxI3IadEHiGn"
    "TDwhp1RLIadcRiGnZEYhp3UeIad9RiGnhTwhp40eIaefRiGnp0YhqAo3IahtNyGonjchqNBGIakBRiGpMUYhqWJG"
    "IamUNyGqAR4hqmRGIaqVPCGqxx4hqypGIauNSyGrvkshq843IavoNyGr8EYhrAAPIawhNyGsUzchrLZGIaznNyGt"
    "IUYhrYRGIa3nRiGuSkYhrntGIa6tRiGvEEYhr0FGIa9zSyGv1jchsAdGIbAhRiGwMR4hsDlGIbBqRiGwnDwhsL5G"
    "IbDXRiGxB0YhsWpGIbHNRiGyMDwhspM8IbL2NyGzJ0Yhs1lGIbOKRiGzvEYhtClGIbRaSyG0akYhtIxLIbTtRiG1"
    "UEYhtYFGIbWzSyG2FkYhtkdGIbZhRiG2eUYhtqpGIbbcRiG3F0Yht0lGIbd6RiG3rEYht91LIbgPRiG4QEYhuFA8"
    "IbhyNyG4o0YhuLM3IbjTRiG5BDwhuTZGIbmZRiG5/EYhujdGIbpHRiG6T0YhuldGIbppPCG6zEYhuy9GIbs/SyG7"
    "R0Yhu2A3IbuSRiG79UYhvFhGIbx6RiG8iUYhvKNGIby5DyG9HB4hvYlLIb3sRiG+HUYhvk9GIb6yRiG/FUYhv3hG"
    "IxjFLSMY9iMjGSg3IxmVKCMZ+FojGlsoIxq+MiMbITcjG1IyIxuEMiMb5zIjHEgKIxy1LSMdGCgjHUlGIx17QSMd"
    "3hQjHkFaIx6kMiMfBy0jH2ooIx+bMiMfzRojH/4jIyA4LSMgaTcjIJsoIyD+HCMhYSgjIcQyIyInLSMiijcjIu1G"
    "IyNQMiMjvS0jJB4yIySBNyMk5C0jJUcoIyWqMiMmDRwjJnBaIyarNyMm3Q8jJ0AoIyejNyMnuzIjJ9QQIygENyMo"
    "Z1AjKMoaIyjsLSMo+zcjKQ03IykVNyMpHQojKS0yIyleMiMpkAUjKcstIyn9MiMqYDIjKpEoIyrDNyMrJi0jK4k3"
    "Iyu6DyMr6S0jLEwUIyy5MiMs0RAjLPIyIy0cLSMtNDcjLU0tIy1/KCMt4igjLkVQIy52RiMuqCgjLwsyIy9uRiMv"
    "2TwjMDw3IzCfNyMw0A8jMQItIzFlMiMxyC0jMfk3IzIrMiMyjjcjMvE3IzNUNyMzvzcjNCIaIzSFLSM0tjcjNOga"
    "IzVLKCM1rigjNhE3IzYzMiM2Qg8jNnQPIzbhNyM3RDcjN6UyIzgILSM4aygjOM4tIzj/NyM5GTIjOTEaIzmUKCM6"
    "AVAjOmQ3IzrHNyM7KkEjO4s3IzvuFCM8UTcjPLRGIz0hUCM9UigjPYQoIz3nECM+Sg8jPq0UIz8QNyM/cTcjP9QU"
    "I0BBLSNAci0jQKRaI0EHMiNBajIjQc0tI0IwMiNCkzcjQsQcI0L2MiNDJzIjQ2FGI0PELSNEJzwjRD88I0RgUCNE"
    "ijIjRLsoI0TtMiNFUDcjRbMjI0YWNyNGeTcjRtxaI0cXRiNHR0EjR6o3I0gNNyNIcCgjSNMyI0k2NyNJmTIjSfwy"
    "I0ppQSNKzDIjSy03I0uQNyNL81AjTCQyI0xWWiNMhy0jTLktI00cMiNNVyMjTYkyI03sKCNOHSMjTk8jI06yQSNO"
    "4zcjTxMyI092MiSfbSMkn9A3JKAzPCSgljIkoPktJKFcKCShv0EkoiI8JKKFMiSi8Dcko1NBJKO2FCSkGTckpHwU"
    "JKStRiSk3x4kpUIyJKVzPCSlpSMkpggjJKZDPCSmdTIkptYjJKc5HiSnnBQkp/83JKhiIySoxUYkqSgUJKmVHiSp"
    "+B4kqlsyJKq8KCSrHx4kq4IyJKuzCiSr5TIkrEgeJKy1FCStGBQkrXs3JK2sPCSt3iMkrkE3JK6iLSSvBUEkr2gU"
    "JK/VNySwOEYksJtBJLD+IySxYTckscQeJLH1NySyJzckspEeJLL0MiSzVzcks7ojJLQdIyS0gDIktOMeJLVGHiS1"
    "qTIktgwyJLZ3MiS22iMktwsjJLc9IyS3oCMkuAMjJLhmIyS4yR4kuSwyJLmZHiS5/Cgkul0tJLrADCS7I0Eku1Qt"
    "JLuGNyS76TckvEwUJLy5LSS9HCMkvX8jJL3iHiS+Q0YkvqYHJL8JFCS/bCMkv9ktJMA8IyTAnygkwQI3JMFlMiTB"
    "yB4kwfkUJMKMIyTC+SMkw1wtJMN0IyTDvzwkxCI8JMSFMiTE6DwkxUsUJMWuQSTGGTckxnwyJMbfKCTHEEYkx0Ij"
    "JMelMiTICDIkyGstJMjONyTJMTIkyZQjJMn/NyTKMEYkymIjJMrFIyTLizwky6UeJMvuIyTMUTwkzLQeJM0hLSTN"
    "hDIkzeUMJM5ILSTOqxQkzw4jJM9xIyTP1C0k0A88JNBBIyTQpCMk0Qc3JNFqHiTRyx4k0i4jJNKRFCTS9CMk0y9G"
    "JNNhLSTTxCMk0/U3JNQnMiTUih4k1O03JNVQMiTVsSMk1hQyJNZPIyTWgRQk1uQjJNdHPCTXeDck16ooJNgNNyTY"
    "cCMk2KEtJNjTIyTZNjIk2aAUJiYKKCYmbTwmJtAeJiczECYnliMmJ7g8JifhEiYn+QomKFw3Jih+NyYopzcmKMkj"
    "JiksHiYpjSgmKfAZJiohPCYqUxAmKrY8JirnNyYrGRAmK3wZJiueHiYrxzwmK+keJixMPCYsrwwmLRIjJi1zPCYt"
    "pDcmLdY3Ji4HDCYuOTcmLpw8Ji8JMiYvbDwmL888JjAyFCYwlTwmMPg8JjFZCiYxvDwmMikKJjKMMiYy7zcmM1Ie"
    "JjODKCYztSMmNBgyJjRJPCY0ex4mNN43JjVJDCY1YQomNYo3JjWsNyY13RAmNg88JjZyPCY2ozwmNtU8Jjc4NyY3"
    "mwomN/43JjhhNyY4kjcmOMQKJjkuHCY5kSMmOfQjJjoWCiY6PwomOlc3JjqIHiY6uigmOx03JjuANyY77R4mPFAj"
    "JjyzPCY9FAwmPXcUJj3aHiY+CzwmPj0jJj6gIyY/DTcmP3A8Jj/TKCZANigmQJkeJkD6PCZBXRAmQcAjJkItECZC"
    "kDwmQvMHJkNWIyZDuR4mRBw3JkR/HiZE4CgmRU08JkWwIyZGEwwmRnY3JkbZNyZHCiMmRzwKJkefKCZIAjcmSGUK"
    "JkjQKCZJARAmSTMeJklkNyZJlgwmSfkKJkobECZKOjwmSlQoJkpcHiZKvwwmSyIyJkuFNyZL6CMmTFUjJky2NyZN"
    "GR4mTXw8Jk3fHiZOQjwmTqU3Jk8INyZPQzcmT3U8Jk/YNyZQOzcmUJw8JlD/HiZRYgomUcU8JlIoHiZSlR4mUvgZ"
    "JlNbGCZTvhkmVCEKJlSCDiZUpDcmVM03JlTlPCZVSDcmVbUoJlYYECZWexQmVt43JldBEiZXURAmV2soJldyKCZX"
    "eh4mV5Q8JlekPCZYBxAmWGg3JljVHiZZBjwmWTg3JlmbNyZZzDwmWf43JlphPCZaxDwmWvU3JlsnCiZbijcmW7s3"
    "JlvtIyZcBzwmXBc8JlwwPCZcQDcmXFg3Jly7NyZdHjcmXYE3Jl3kNyZeFR4mXkc3Jl54KCZeqjcmXts8Jl8NNyZf"
    "cDcmX903JmA9HiZgoB4mYQM3JmFmHiZhyR4mYiw3JmKZIyZi/DwmY18jJmPCHiZj2iMmZAMeJmQjECZkhjwmZLcj"
    "JmTpNyZlTDcmZbkoJmYcNyZmfygmZuIoJmcTHiZnRTcmZ6g3JmgJPCZobDcmaNk3JmmfNyesdgcnrKgoJ60LNyet"
    "biMnrdEOJ640KCeuoRQnrwQOJ69nKCevyg4nsCsoJ7BcDiewjkYnsPEoJ7FUHiexwQ4nsiQQJ7KHNyey6hQns01B"
    "J7OwFCe0EUYntHQoJ7ThFie1RBwntacoJ7YKKCe2bRQnttAOJ7czIye3lgcnuAE3J7hkGie4xyMnuSojJ7mNKCe5"
    "vgcnufAeJ7pTDie6tiMnuxkaJ7t8KCe7ljcnu+cOJ7xKFCe8exonvK0OJ70QQSe9cw4nvdYUJ745Die+nC0nvwkQ"
    "J79sHie/zCMnwC9BJ8BgNyfAkg4nwPVGJ8FYFCfBkw4nwcUOJ8IoKCfCizcnwu4jJ8NRDifDsiMnxBUUJ8R4DifE"
    "5UYnxUgUJ8WrKCfGDkEnxnEjJ8bUDifHNygnx5hBJ8gFKCfIaA4nyMtGJ8kuNyfJkSgnyfQHJ8olDifKVygnyogO"
    "J8q6DifLHQcny04OJ8uIFCfLuTcny+sYJ8xODifMfyMnzLEjJ80UIyfNRQ4nzXcQJ83aLSfOPSMnzm43J86gKCfP"
    "DRYnz24OJ8/RFifQAkEn0DQOJ9CXQSfQ+gcn0V0OJ9HAByfSLRYn0pA3J9LzRifTVA4n07ctJ9QaIyfUfSMn1OBB"
    "J9VNIyfVsA4n1hMHJ9Z2IyfW2RQn1zo3J9edNyfYABQn2G0UJ9jQDifZMw4n2U0oJ9mWBSfZ+RQn2lwOJ9q/Difb"
    "ICMn240aJ9vwQSfcUyMn3LYUJ9znRifc9ygn3RkUJ91KRifdfDcn3d8WJ95CKCfepQ4n3xAUJ99zFCff1iMn4Dkj"
    "J+CcDifg/0En4WIoJ+HFByfiKBQn4pUoJ+L2QSfjWUEn47wOJ+QfRifkgign5OUaJ+VIKCfltRQn5hhBJ+ZJDifm"
    "2xQn5z4jJ+ehQSfoBA4n6HEUJ+jUDifpN0Yn6ZooJ+n9IyfqYCgn6sEjJ+skQSfrdxon65EUJ+v0DifsVw4n7LoO"
    "KTNGRikzqSMpNAwPKTR5ECk03BIpNT8eKTWiRik2BSMpNmhGKTbJHik3LBApN5kjKTf8ECk4LRApOF8eKTjCIyk5"
    "JUYpOYgQKTnrRik6ThApOrkPKTscECk7fwwpO+IeKTwTDyk8RUYpPKhGKTzZIyk9Cw8pPW48KT3RECk+NA8pPp8Q"
    "KT8CIyk/ZTwpP8hGKUArRilAjhApQPEQKUFURilBjx4pQcEQKUIkEClChSMpQugPKUNLIylDrgcpRBFGKUR0EClE"
    "4UYpRUQMKUWnIylGCiMpRmpGKUbNEClHMBApR50jKUgARilIYxApSMYQKUkpRilJjEYpSe8jKUpQRilKvUYpSyBG"
    "KUuDIylL5kYpS/ZGKUwQEilMSRApTKwjKU0PMilNcjwpTdUMKU5AEClOo0YpTwZGKU9pEClPzBApUC88KVCSIylQ"
    "9QwpUVgeKVHFDClSJkYpUokQKVLsIylTTxApU7JGKVQVEClUeB4pVOUQKVVIIylVqwwpVdxGKVYMIylWbw8pVqAj"
    "KVbSHilXNRApV5gQKrnkLSq6USgqurQHKrsXHiq7eiMqu90FKrweHiq8QBIqvXEjKr3ULSq+N0YqvpoeKr79Riq/"
    "YBIqv8MoKsAmIyrA7CgqwVceKsG6CirCHUYqwoBGKsLjRirDRhIqw6lGKsQMEirEeQoqxNwUKsU9HirFoEYqxgMK"
    "KsZmHirGySMqxywjKseZHirH/DwqyF8oKsjCHirJIyMqyYYUKsnpRirKTCgqyrkjKsrqRirLHEYqy38oKsviPCrM"
    "RQoqzKgUKs0IRirNdR4qzdhGKs47EirOnkYqzwEoKs9kRirPxyMq0CojKtCNIyrQ+EYq0VseKtG+HirSIQoq0oQj"
    "KtLnIyrTShQq060KKtQQHirUfSgq1N5GKtVBKCrVpCMq1gcoKtZqRirWzSgq1zAOLECMQSxA70EsQVIeLEGDHixB"
    "tTwsQhhBLEJ7IyxC3h4sQ0EjLEOkFCxEDyMsRHIeLESjQSxE1SMsRThBLEVpQSxFm0EsRf48LEZhHixGxDwsRzFB"
    "LEeUHixHxSMsR/VBLEgmHixIWDIsSLseLEjsFCxJHh4sSYEULEnkQSxKUTwsSoIeLEq0QSxLF0EsS3ojLEvbQSxM"
    "PhQsTKFBLEzDQSxM7DIsTQQULE1xFCxN1CMsTjcyLE6aIyxO/TwsT2BBLE+RIyxPwUEsT/JBLFAkQSxQkUEsUPQj"
    "LFFXQSxRukEsUh1BLFKAFCxSsUEsUuMjLFMUHixTRh4sU7BBLFQTPCxURCMsVHZBLFTZQSxVPCgsVZ9BLFYCFCxW"
    "ZQcsVsgULFc1QSxXlkEsV/lBLFhcQSxYvxQsWSI8LFmFByxZ6EEsWlUjLFq4MixayDIsWukyLFr5PCxbE0EsWxsj"
    "LFt8Hixb30EsXEJBLFylPCxdCEEsXXUHLF2mQSxd2EEsXjtBLF6eHixfAR4sX2IULF/FQSxgKB4sYJUeLGD4Mixh"
    "Wx4sYb4eLGIhQSxihEEsYucPLGNIQSxjtUEsZBhGLGR7QSxk3kEsZUEjLGWkHixmB0EsZmoeLGbNQSxnOCMsZ2kH"
    "LGebQSxn/h4saGEyLGjEMixpJx4saYoeLGntMixqByMsah4eLGo4QSxqUB4saotBLGq9FCxrHhQsa4FBLGvkFCxs"
    "FTIsbEdBLGyqRixtDRQsbXAeLG2rQSxt3UEsbkAoLG5xHixuozIsbwRBLG9nFCxvykEscC0oLHCQQSxw/UEscWA8"
    "LHHDFCxyJjcscokULHLqQSxzTUEsc7BBLHQdPCx0gEEsdLEULHTjHix1RhQsdakeLHYMMix2bxQsdtA8LHc9QSx3"
    "oCMseANBLHhmQSx4yR4seSxBLHldIyx5jzwsefIULHpVFCx6v0EseyIjLHuFIyx76CgsfBlBLHxLMix8rhQsfREo"
    "LH10FCx94TwsfkQeLH6lMix/CAcsf2sULH/OIyyAMTwsgJQeLIEBFCyBZCMsgcc8LIH4MiyCKiMsgosyLILuHiyD"
    "UUEsg7QULIPWQSyD70EshCFBLISEPCyE5yMshUpBLIWtHiyGEB4shnEjLIbURiyHQSMsh6QjLIfVQSyIB0EsiDgo"
    "LIhqQSyImxQsiM1BLIkwIyyJYUEsiZMjLIn2NyyKYTwsipIjLIrEMiyK9UEsiycHLIuKQSyL7UEsjFBBLIyBQSyM"
    "szwsjRY8LI15QSyN3EEsjfYFLI4XQSyORzwsjqo8LI8NQSyPcEEsj9MjLJAEQSyQNiMskJkeLJD8FCyRaSMskcwU"
    "LJItByySXkEskpA3LJLzPCyTViMsk7lBLJPqIyyUHDIslIlBLJTsQSyVT0EslbJBLJYTIyyWREEslnY8LJbZHiyX"
    "CkEslzweLJepIyyYDB4smG8ULJigMiyY0iMsmOoyLJkDFCyZNSMsmWZBLJmYHiyZ+SMsmhtBLJoqHiyaXB4smslB"
    "LJssHiybXTwsm49BLJvyQSycVUEsnLhBLJ0bHiydfiMsnelGLJ4aMiyeTB4snq9GLJ8SQSyfdUEsn9hBLKA7QSyg"
    "bDwsoIYULKCeQSyhATwsoWQjLKHOIyyiMSMsopQHLKLFQSyi9yMso1oyLKO9IyykIEEspI1BLKS+FCyk8DIspVMy"
    "LKVrPCylhDwspbRBLKYXMiymekEspt0yLKdAQSynrR4sqBAeLKhBMiyoc0EsqNZBLKk5QSypmh4sqf1BLKpgPCyq"
    "zR4sqzAFLKuTMiyr9kYsrFkjLKy8MiytHyMsrYAyLK27FCyt7UEsrlBBLK6zMiyvFkEsr3kyLK/cHiywPx4ssKIy"
    "LLEFQSyxNjIssXAeLLGhQSyx0x4ssjYHLLJnQSyymR4sssoULLLaPCyy/CMss18eLLPCHiy0JR4stFYeLLSIQSy0"
    "9UEstVZBLLW5QSy16kEsthxBLLZ/QSy24jIst0UyLLeoPCy4FQcsuEZBLLhORiy4VkEsuHhBLLjbQSy5PEEsuW1B"
    "LLmfMiy6AhQsumU8LLqWIyy6yB4suzUyLLuYFCy7+x4svF5BLLzBMiy9IjIsvYUjLL3oFCy+VRQsvrhBLL7pQSy/"
    "GxQsv35BLL/hFCzAREEswKcULMEIMizBQzwswXU8LMGmPCzBth4swdgHLMIJIyzCOyMswp5BLMLPQSzDARQsw2RB"
    "L03IKC9OKygvTo4aL07xGi9PVB4vT8EeL1AkGC9Qhx4vUOo8L1FLQS9Rrh4vUhEeL1J0Hi9S4R4vU0QeL1OnGi9T"
    "vx4vVAo8L1RtHi9U0BovVTEaL1ViGC9VlBwvVgEeL1ZkFC9Wxx4vVyoaL1eNGi9X8EEvWFMeL1iEKC9YthYvWSEU"
    "L1mEHC9Z5xQvWkoYL1qtQS9bEB4vW3MeL1vWHC9cBxQvXDkoL1ycIy9dByMvXWocL13NIy9eMBovXpMeL17EKC9e"
    "9kEvX1keL1+8Mi9gKSgvYIweL2DsFC9hTyMvYbI8L2IVGi9ieBQvYuUcL2NIFi9jqxovZHEWL2TSFC9lNRgvZZgF"
    "L2YFGC9maBQvZssoL2cuPC9nX0EvZ5EHL2f0GC9oVxgvaLgoL2klGi9piB4vaesoL2pOIy9qsR4vaxQcL2t3FC9r"
    "2hQvbD0eL2yoHi9tCxQvbW4yL22fQS9t0R4vbjQaL26XMi9uyEEvbvoyL29dFi9vwB4vcC0eL3COFC9w8R4vcVQo"
    "L3GFFC9xt0EvchpGL3JLQS9yfRwvcuAUL3NNHi9zsB4vdBMUL3R0By901xgvdToWL3WdGi92AB4vdm0eL3bQHi93"
    "Mx4vd5YeL3f5Hi94WhoveL0eL3juMi95IB4veY0aL3nwGC96UyMverYaL3sZHC97fB4ve98eL3xAHi98exgvfK0Y"
    "L30QHi99cygvfdYcL345By9+nB4vfs0eL37/Mi9/Yhovf8UYL4AwQS+Akx4vgPYWL4FZHC+BvBQvgh8oL4KCHi+C"
    "5TIvg0geL4O1Hi+EFh4vhHkeL4TcFC+FPygvhaIaL4YFHi+GNh4vhmgeL4bVHi+HOB4vh5sUL4f7KC+IXhoviMEe"
    "L4kkHi+JXxQviZEUL4nCKC+J0kEvifQeL4pXKC+Kuh4vix0UL4uAGC+L4RgvjEQoL4x/QS+MsRgvjRQWL413HC+N"
    "2jIvjj0eL46gHC+PAx4vj2YeL4/RQS+QNBovkJceL5D6GC+RXR4vkcAUL5IjIy+Shh4vkukeL5MMQS+TNAcvk0we"
    "L5O3FC+UGhQvlH0YL5TgFC+VQx4vlaYeL5YJBy+WbBovltkyL5c8FC+XnR4vmAAyL5hjGC+YxigvmSkUL5mMQS+Z"
    "+RgvmlwWL5q/Iy+bIh4vm1MeL5uDFC+b5igvnBc8L5xJHi+crDIvnRkUL518Hi+d3xQvnkIoL56lHi+exx4vnuZB"
    "L58IKC+faSgvn8weL6A5Gi+gahgvoJwYL6D/Hi+hYhYvocUoL6IoGi+iixQvou4eL6NZGC+jvB4vpB8YL6SCFC+k"
    "s0EvpOUaL6UWPC+lJjIvpUgUL6WrHi+mDhovpnEeL6bUHi+nPx4vp6IeL6gFIy+oaBwvqMsjL6kuKC+pSBgvqZEa"
    "L6n0FC+qYSgvqpIUL6rEHi+rJRwvq4gHL6vrGC+sTkEvrLEeL60UHi+tgR4vreQjL65HKC+uqhwvrwoYL69tHi+v"
    "0BovsD0cL7CgKC+xAygvsWY8L7HJKC+yLBQvso8UL7LAHC+y8BQvs10eL7PAQS+0IxwvtIYUL7TpKC+1TCgvta8y"
    "L7XgKC+2EigvtnUeL7amHi+24B4vtxEyL7chQS+3Qx4vt6YUL7gJHi+4K0EvuDoyL7hKHi+4XB4vuGweL7jPGC+5"
    "MigvuZUeL7n4Mi+6ZSgvusYeL7spGi+7jBYvu70oL7vvHC+8Uh4vvLUYL70YQS+9hRwvvegeL75LKC++rB4vvw8e"
    "L79yHi+/1RQvwDgWL8ClIy/BCDIvwTkyL8FrHC/BzgcvwjEaL8KSHi/Cw0EvwvUUL8NYFC/DxSMvxCgeL8SLGi/E"
    "vBQvxO4eL8UfQS/FUSgvxbQeL8YXFC/GeBQvxuUoL8cWFC/HSB4vx6sUL8gOHi/IcRovyNQjL8k3FC/Jmh4vyf0U"
    "L8poMi/Ky0Evyy4eL8uRKC/L9B4vzFcoL8y6Hi/NHR4vzYAUL83tHC/OTh4vzrEeL88UHi/Pd0Evz9oeL9A9Hi/Q"
    "oB4v0Q0UL9E+Gi/RcBQv0dMUL9I0QS/Slx4v0voeL9NdHi/TwB4v1C0eL9SQFC/U8zwv1VYcL9W5Hi/WGRQv1kpB"
    "L9ZkHi/WfDIv1ulBL9dMIy/XfTIv168UL9fgKC/YEhov2HUyL9jYFC/ZOzwv2Z4eL9oJPC/abB4v2s8UL9syQS/b"
    "lSgv2/g8L9wIKC/cKR4v3EMyL9xbBy/cjBQv3L4YL90hMi/dhBwv3b9BL93vKC/eUkEv3rUjL98YMi/fex4v394o"
    "L+AAQS/gQQcv4KQYL+ERHi/hdBwv4dUeL+I4Mi/imx4v4v4jL+MvKC/jYR4v48QeL+QxGC/kQR4v5GIyL+RyGC/k"
    "ejIv5JQeL+T3Iy/lWjwv5bsaL+YeHi/mgSgv5rJBL+bkQS/nURgv57QYL+gXHi/oehQv6N0YL+lAHi/poRQv6gQY"
    "L+o/By/qcRgv6tQUL+s3Hi/rmigv67IYL+vLPC/r/Rgv7GAUL+zDGC/s9EEv7SYYL+2RQS/t9Acv7lcoL+66Iy/v"
    "HUEv74AeL+/jGC/wRh4v8KkoL/EMHi/xdzIv8docL/I9HC/ybkEv8qAUL/MDIy/zZigv88keL/QsQS/0mRQv9PxB"
    "L/VdHC/1wCgv9fE8L/YjHC/2higv9ukeL/caQS/3TCgv97koL/gcFC/4fx4v+OIcL/lDHi/5phwv+gkYL/psMi/6"
    "px4v+rcyL/rZHi/7PB4v+58aL/vQQS/74B4v/AIUL/xlBy/8yB4v/SgjL/1jQS/9lRwv/fgjL/5bQS/+jCgv/pxB"
    "L/6+GC/+7ygv/yEeL/+EHi//5xgwAEoUMAB7GjAAlRgwAK0UMAEYHjABexQwAd4yMAIPMjACQUEwAqQoMAMHIzAD"
    "OEEwA2oYMAPNHjAD/jwwBJ0UMAT+MjAFYRQwBcQaMAYnHjAGihQwBu0UMAdQHjAHvR4wCCAeMAiDGjAItDIwCOQo"
    "MAlHKDAJqhwwCg0cMApwGDAK3SgwC0AYMAujQTAL1BowDAYWMAxpHjAMyhwwDS0eMA1eQTANkCMwDf0HMA5gGDAO"
    "wxgwDyYUMA+JIzAP7CMwEE8eMBCAHjAQsB4wER0eMBFOFDARgBowEeMeMBJGFDASqSMwEssUMBLqQTATDB4wE28e"
    "MBPSHDAUNR4wFKAeMBUDHjAVZkYwFckeMBYsIzAWjyMwFvIeMBdVHjAXuBQwGCUeMBiGKDAY6RowGQMyMBkqQTAZ"
    "TEEwGa8cMBoSKDAadR4wGtgeMBtFFjAbqB4wHAsaMBxsIzAczxwwHTIoMB2VKDAd+EEwHmUYMB7IBzAfKygwH44U"
    "MB/xBzAgUhowILUeMCDmGDAhGB4wIYUeMCHoHjAiGUYwIktBMCKuBzAjER4wI3QHMCPXGjAkQRowJKQ8MCUHFjAl"
    "ahQwJc0eMCYwKDAmk0EwJvYUMCdZHjAnvBgwKCcYMCiKHjAo7RgwKVAeMCmzKDAp5BwwKhZBMCp5PDAq3AcwK0kY"
    "MCusIzAsDUEwLHA8MCzTFDAtBBQwLR4YMC02FjAtWBYwLYFBMC2ZGjAt/BgwLmlGMC6aPDAuzCMwLy8HMC+SGDAv"
    "8xQwMFY8MDC5HjAxHBowMYkeMDHsFDAyTxgwMrIeMDMVHjAzeBgwM6keMDPZFDA0PBQwNKkaMDUMGDA1PRQwNW8Y"
    "MDXSHjA2NR4wNpgjMDb7HjA3Xh4wN8keMDgsGjA4jxgwOPI8MDlVIzA5hkEwObgUMDobKDA6fhgwOuEeMDtEFDA7"
    "fxQwO68UMDvgHjA8EkEwPHUeMDzYHjA9OxwwPZ4eMD4BHjA+Mh4wPmQoMD7RFDA/NBQwP5UeMD/4KDBAWxowQIwy"
    "MEC+HjBBITIwQVJBMEGEHjBBvxgwQc8eMEHxFDBCIjIwQlRBMEK3GDBDGhgwQyoUMENEGjBDSwcwQ3seMEPeFDBE"
    "QR4wRKQYMEURFDBFdB4wRdcYMEY6HjBGnRwwRwAcMEdhGjBHxBgwSDFGMEiUIzBI9x4wSQ8cMEk4FDBJWhgwSb0e"
    "MEogHDBKgxQwSuYeMEtQHjBLsxwwTBYeMEx5HjBM3B4wTT8YME1hBzBNcCgwTXgaME2KHjBNohgwTgUcME5oHjBO"
    "1SgwTzYWME+ZHjBP/BYwUF8aMFDCHjBRJRgwUYgjMFH1MjBSWCgwUrsaMFLsQTBTHB4wU38oMFPiFDBURR4wVKge"
    "MFUVGDBVeBgwVdsUMFY+HjBWoR4wVwJBMFczHjBXZSMwV8gjMFg1BzBYmBQwWPsWMFleKDBZwRQwWiQWMFqHKDBa"
    "6B4wWyMeMFtVHjBbuBwwXBseMFxMKDBcfhowXOEeMF1EFDBdpygwXgoeMF5tHjBe2DIwXwkUMF87GDBfnhQwYAE8"
    "MGBkQTBghh4wYK9BMGDHGjBg4UEwYRIUMGEqIzBhW0EwYY0aMGG+KDBh8DIwYl0yMGK+MjBi1jIwYv8oMGMhGDBj"
    "UhowY4QHMGPnFjBkShwwZK0eMGUQQTBlfR4wZeAYMGZDGDBmpB4wZwceMGdqHjDUZhQw1IgUMNSpFDDUyRgw1SwS"
    "MNVnFDDVmRAw1fweMNZfFDDWwhAw1yUaMNeIFDDX6RQw2EwUMNiHFDDYuRAw2RwMMNl/EjDZ4hIw2kUUMNqoEjDb"
    "CxQw224SMNvZFDDcPDIw3J8UMNzQEjDdAhYw3WUQMN2WFDDdyBgw3fkYMN4rEjDeXBQw3o4WMN7xEjDfVBQw378U"
    "MN/wFDDgIh4w4DoYMOBbFDDghRQw4OgUMOD4EjDhEhIw4RkSMOFLHjDhrjww4hE8MOJ0EjDi4R4w40QUMOOlFDDj"
    "1hQw5AgUMORrEjDknDww5M4eMOT/FDDlMRQw5ZQSMOXPEjDmARIw5jISMOZkFDDmxxQw5yoUMOdbEjDnigww55IU"
    "MOesEDDnzRIw5+0MMOgeFDDoOBQw6FAMMOi9BzJbBBAyWz8jMltxDjJbgRwyW4kOMluiDjJb1BQyXDcaMlxoCjJc"
    "mhkyXP0eMl1gDjJdww4yXiYjMl5IDDJeVxwyXpEMMl70IzJfJQwyX1cjMl+6EjJgHQwyYIAjMmDjGjJhRgoyYakO"
    "MmHaCjJh9A4yYgwKMmJ3CjJiqAwyYtoWMmM9HjJjbhoyY34KMmOgHDJkAwwyZDQjMmRmCjJkyRAyZSwOMmWZEjJl"
    "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"
    "wxQ+vPUQPr1YEj69uxI+vh4QPr6JFD6+7BA+v08UPr+yEj7AFRY+wHgSPsDbGD7BPhI+wW8SPsGhEj7CBBI+wj8U"
    "PsJvFj7C0hI+wzUQPsNmFD7DmBI+w/sSPsQVEj7ELBI+xF4YPsTBED7FJAw+xUYSPsVfEj7FkQ4+xfQQPsZVFD7G"
    "uA4+xxsOPsd+DD7HrxQ+x+EYPshEFD7IsRI+yRQWPsl3Dj7J2hI+yjoYPsqdFD7LAA4+y20SPsueEj7L0BQ+zAES"
    "PswzEj7MlhI+zPkQPs0bFD7NKhI+zVwSPs2NEj7Nvxg+ziAQPs5bEj7OjRQ+zvAQPs9TDj7PthA+0BkYPtB8Ej7Q"
    "3xI+0UIUPtGlFD7R1hQ+0hASPtJBEj7Scxg+0tYWPtLeEj7S5hI+0wcUPtMXFD7TMRA+0zkUPtOcED7TzRI+0/8Q"
    "PtRiGD7UxRA+1SgUPtWVEj7V9hg+1lkYPta8ED7XHxg+14IUPtezEj7X5RI+2EgYPti1GD7ZGBQ+2UkUPtl7FD7Z"
    "3BQ+2j8UPtpwDD7aohI+2tMUPtsFFD7baBA+29UMPtw4FD7caQw+3JsYPtz+FD7dYQw+3ZIQPt3CED7eJRQ+3lYS"
    "Pt6IGD7e9Rg+3w0QPt8mFD7fWBQ+37sQPuAeED7gTxQ+4IESPuDkDD7hFRI+4UcUPuGoHj7iFRQ+4ngUPuKpEj7i"
    "2xI+4wwUPuM+FD7joRA+5AQUPuRnFD7kmBQ+5MoSPuUtEj7lmBA+5fsSPuYsEj7mPBI+5l4OPubBED7nJAw+54cU"
    "PufqFj7oGxI+6E0QPuiwFD7pHRI+6X4UPunhEj7qRBI+6qcYPusKEj7rbRI+69ASPuw9GD7soBQ+7LAUPuzRFD7t"
    "AxI+7TQYPu1kEj7tdBI+7ZUSPu3HEj7uKhg+7o0SPu7wFD7vXRI+78AQPvAjFD7whhQ+8OkYPvFJEj7xrBA+8hkU"
    "PvJ8ED7yrRQ+8t8SPvMQEj7zQgw+83MWPvOlED70CBI+9DkSPvRrEj70zhg+9TkUPvWcFj71/xI+9jAOPvZAFD72"
    "YhQ+9pMSPvbFEj73KBA+94sSPve8FD731gw+9+4YPvhRFj74tBg++R8QPvmCFD755RY++kgYPvqrEj77DhQ++3EU"
    "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"
    "QbOJFEGzqxJBs7oQQbPPFEGz7BBBtA4MQbQnDEG0NxBBtFcUQbSIEEG0mBRBtLoUQbTSFEG1HRJBtYAUQbWQFEG1"
    "sRRBtcsWQbXjEkG1/RRBthQUQbZGEEG2dxJBtqkcQbcMFEG3LhRBt0cSQbdPDkG3eRJBt9wjQbfsFEG39BRBuA0U"
    "QbgdFEG4PRRBuG4QQbigKEG5AxRBuWYUQbnJGUG5+hRBuiwSQbpnFEG6mQdBuvwHQbtfEkG7ZxRBu3cUQbuYDEG7"
    "wgxBvCMUQbxUFEG8bhJBvIYSQbzpDEG9GhRBvUwUQb25FkG90RJBveoUQb4cFEG+fwxBvrAUQb7iFEG/RQ5Bv3YU"
    "Qb+oFEHACRRBwDoKQcBsEkHAhhRBwKcUQcDZCkHBChRBwTwOQcGfFEHCAhRBwjMSQcJDFEHCZRRBwpYcQcLIFEHC"
    "+RRBwysUQcOOGUHDvxJBw/kUQcRcEkHEvxRBxSIUQcU6EkHFWxJBxYUUQcWNFEHFpxlBxb4UQcXoFEHGChZBxhkc"
    "QcYzFEHGSxRBxnwSQcauFEHG3yNBxxESQcdCEEHHXBJBx3QUQcffKEHIQhZByFIZQchaI0HIcyNByKUjQcjHFEHI"
    "1hJByOYUQckIGUHJaxJByYUQQcnOI0HKMRRByksSQcpbEkHKlBRByqYUQcq2EkHKzyNByt8SQcrvEkHLARRBy2QU"
    "QcutDkHLxRRBy/YSQcwoFkHMShBBzFkUQcxzFEHMixRBzLwUQczuFEHNHxRBzTkZQc1BDEHNURJBzWsSQc17EkHN"
    "ghBBzZwSQc20GUHOIRJBzikZQc4xFEHOUhRBzmIUQc6EFEHOtRRBzucUQc9KFEHPexRBz6sSQc+zFEHPzRZBz+QO"
    "Qc/+DEHQDhRB0HESQdDUFEHQ9hRB0Q8MQdEfB0HRLxRB0UEHQdFRFEHRYRRB0XoUQdGSEEHRpBJB0gcUQdI4EkHS"
    "ahBB0s0UQdMwFEHTYRRB05EUQdOrFEHTsxJB08ISQdPUFEHT3BRB0/QQQdQWFEHULxJB1D8jQdRhEEHUxBRB1ScQ"
    "QdU3EkHVWBBB1WAZQdVoI0HVghRB1YojQdW0DEHVuxRB1e0jQdZQFEHWgRJB1psQQdajFEHWswdB1xYFQdeAFEHX"
    "sRRB18EUQdfjFEHX+xJB2A0SQdgUEkHYJBRB2EYUQdipHEHYsRRB2LkjQdjaFEHZDBRB2T0SQdlvFkHZoBRB2dIZ"
    "Qdo1FEHaZhJB2pgSQdsFFEHbNhRB22YSQdvJFEHcLBRB3I8UQdzyHEHdDBBB3RQUQd0jEkHdPRRB3VUSQd24FEHe"
    "JRRB3j0UQd5WEkHeiBRB3usWQd8cEkHfLBxB30wjQd+vHEHgEhRB4EMMQeB1KEHg2CNB4UUUQeF2FEHhqBJB4gsU"
    "QeI8EEHibhBB4tEUQeMCFEHjMhRB42MUQeOVI0Hj+BlB5GUcQeTIDkHk2BRB5OAUQeToFEHk+RBB5QEUQeUREkHl"
    "IxRB5SsZQeWOFEHllhJB5Z4ZQeXxB0HmVBBB5rcUQecYDEHnhRRB55UWQee2FEHn6BRB6EsUQeh8EkHohBBB6IwU"
    "QeiuFkHpERJB6XQjQenXFEHp3xRB6fkQQeoIEkHqOhZB6p0HQesIB0HraxRB684UQevmFEHsBxRB7DEUQexBFEHs"
    "YhBB7JQUQezFEkHs9xRB7SgQQe1CFEHtWhRB7YsWQe2lFEHtvRRB7iASQe5bEkHujRRB7u4UQe9REEHvtBJB8BcS"
    "QfAxFEHwSBlB8HoUQfCcEkHwqxJB8L0UQfDFFEHw1RZB8N0SQfFAEkHxWhJB8WIUQfGDEkHxrRJB8hAUQfIoEkHy"
    "QRRB8nMUQfKkFEHy1BJB8zcUQfNoEkHzihRB85ojQfPLEkHz/RRB9BcQQfQnFEH0LhRB9EgjQfRgHEH0zRlB9N0O"
    "QfTlFEH07RJB9P4UQfUwFEH1kxRB9fYMQfYnEkH2WRRB9roKQfcdFEH3gBRB9+0MQfgeFEH4UBRB+IEjQfizFEH5"
    "FhRB+XkUQfmqFEH5uhJB+dwSTEwLI0xMPDxMTaEtTE4EWkxOZy1MTpgjTE7KLUxPKyhMT45aTFAbI0xRJChMUrAt"
    "TFMRKExTdDJMU69aTFPhPExURCNMVKcoTFVtRkxV0A9MVjMyTFaWKExWxyhMV2QjTFeVLUxXx25MV/hGTFgqPExY"
    "vh5MWOBaTFjwHkxZth5MWectTFoZHkxafEZMWucjTFtKMkxcEC1MXHMoTFzWHkxdOS1MXZweTF4JLUxebCNMXswy"
    "TF8vLUxfYChMX5JuTF/DI0xgWChMYShaTGFxLUxhiy1MYe4yTGKyHkxjeChMY7MeTGPDKExj5ShMZBYtTGRIPExl"
    "DiNMZjdQTGcFI0xnaB5MZ8soTGguPExokSNMaMIjTGlPRkxpVy1MabojTGodHkxqPzxMak4tTGpoKExqiB5Ma7Ej"
    "TGwUHk3SRlBN0qlQTdLaZE3TDDxN00dQTdN5PE3T3FBN1D88TdUFZE3VyVBN1pk8TdbKUE3W/FBN119kTdglUE3Y"
    "iFBN2OtQTdkNWk3ZHFBN2U5kTduoUE3cC1BN3C1kTdxWPE3cXmRN3GZQTdxuUE3cyWRN3QJkTd2fWk3d0GRN3gJQ"
    "Td5lWk3elmRN3shkTd75UE3fAWRN3xNkTd8rHk3fTVBN31xQTd+OZE3f8TxN4FRaTeDBUE3g8lpN4SQ8TeFVUE3h"
    "6FpN4ks8TeN0UE3jjmRN455kTeOvZE3j4TxN5Kc8TeUKUE3lalBN5c1kTeX+ZE3mGGRN5jA8TeZSUE3ma2RN5p1Q"
    "TedjZE3nrFpN58ZaTefWUE3o71pN6VBQTem9UE3p7mRN6f5QTeoGZE3qDmRN6iBaTeooZE3qMGRN6jhQTepAWk3q"
    "UVBN6llaTephZE3qaVBN6ntkTeqDWk3qi1BN6sQ8Ter2Wk3rF1pN60lQTevdPE3sDzxN7EBkTexaUE3scmRN7IxQ"
    "TeyjUE3tQDxN7WA8Te15UE3to1BN7dRQTe3sUE3t/jxN7gZQTe4wWk3uP1BN7mE8Te5pZE3umlBN7sw8Te96ZE3v"
    "kjxN7/VQTfAfUE3wJlBN8DhkTfBAUE3wUFBN8FhGTfCTUE3wo2RN8KtQTfDFWk3w1VpN8OVkTfD2UE3xJmRN8Vda"
    "TfGJPE3x7DxN8k9kTfKAZE3yskZN8xVaTfN4UE30SFpN9HlQTfSrZE303GRPWLIYT1jkKE9ZBh5PWR8WT1kvI09Z"
    "US1PWYIoT1m0Hk9aeiNPWqs8T1rdRk9bo0ZPW708T1vUFk9cBhRPXNQQT103LU9dmhZPXf0WT14uKE9eYChPXsMW"
    "T18mLU9fiRhPYOstT2GxMk9iRjJPYqkcT2N5FE9koC1PZQMeT2VmI09lyS1PZiwWT2ZnEE9mdzxPZpkUT2dfMk9n"
    "wihPZ+MWT2f6Rk9oIy1PaIYYT2jpHk9pGhhPaUwjT2m5PE9qHC1Pak0jT2p/FE9qsDJPauI8T2tFHE9rdhBPa6hQ"
    "T2vZMk9sCBRPbEMeT2x1KE9s2BRPbTtGT22eFE9tzxZPbd8oT235KE9uCSNPbhFGT27HGk9vKiNPb40tT3C+KE9x"
    "ISNPcYQ8T3HnI09ySi1Pcq1GT3MQHk9zfR5PdEEyT3TVPE91OB5PdWoeT3XNMk917y1PdjAeT3cAHk93Y0ZPd8Qo"
    "T3gnMk94WB5PeO1GT3lQFE95vSNPeiAUT3qDB0965hRPe0ktT3wNHk98Ph5PfHAWT3zLFE99QEZPfXEyT34GFE9+"
    "aSNPfswjT38vRk9/URhPf2AeT3+QGE9//ShPgC4UT4BgHk+Awx5PgSYUT4HCFE+B7BRPgrIeT4MVHk+DgC1PhEYU"
    "T4SpI0+FDBpPhW8YT4XSHk+GNR5PhpgUT4cFKE+HZhZPh5cUT4fJGk+ILC1PiF0eT4iPEE+JVShPibgjT4olRk+K"
    "iDxPiustT4scMk+LTBZPi30oT4ufMk+LrzxPjNgeT41FUE+OCy1PjjweT45MMk+ObihPjp8eT47RFk+PMjJPj2M8"
    "T4+VN0+QyBZPkSsUT5GOPE+R8R5PklQtT5J2PE+SjRRPkp88T5K3Rk+TIRZPk+cUT5P/KE+UGEZPlEojT5StFE+V"
    "EChPlXMoT5WkPE+V1hZPljkeT5acHk+XBxRPmDAeT5iTHk+YxChPmikaT5qMMk+bUB5Pm7MyT5wWI0+ceSNPnUkj"
    "T52sI0+e0zxPnwQeT582PE+f/EZPoFceT6DMHk+hLxRPoZIUT6HlLU+h9R5PolgeT6K5Gk+jHBZPo4kjT6O6LU+j"
    "7BRPpB0UT6RPPE+kgB5PpLIUT6UVMk+leDJPpYAeT6WaFE+lqShPpdtGT6Y+FE+mqUZPptoeT6cMHk+nPR5Pp29G"
    "T6eoHk+nuBRPqDUjT6hmB0+omChPqPseT6lORk+pXkZPqo8UT6rYRk+rTRRPq7goT6wbFE+sTDJPrH4WT6yvHk+s"
    "yTxPrOEyT61EFE+tsR5PreIoT64UI0+udShPrqYjT687KE+vniNQ34wF"
)


@dataclass(frozen=True)
class FiscalModuleAssessment:
    """Result of the territorial criterion without inferring CAF qualification."""

    status: str
    status_label: str
    municipality_code: str
    area_ha: str
    module_size_ha: str
    module_count: str
    four_modules_ha: str
    declared_module_count: str
    calculation_source: str
    consistency_note: str
    source_rule: str
    source_url: str
    source_date: str
    scope: str
    rationale: str
    technical_action: str
    family_farming_qualification: str

    def as_dict(self) -> dict[str, str]:
        """Return a JSON-safe representation used by UI and reports."""
        return asdict(self)


@lru_cache(maxsize=1)
def fiscal_module_sizes() -> dict[str, Decimal]:
    """Decode the official municipality-code to hectare-size mapping."""
    raw = base64.b64decode(_PACKED_MODULES)
    if len(raw) % 4:
        raise ValueError("Cadastro de módulos fiscais corrompido.")
    values: dict[str, Decimal] = {}
    for (packed,) in struct.iter_unpack(">I", raw):
        code, hectares = divmod(packed, 256)
        values[f"{code:07d}"] = Decimal(hectares)
    if len(values) != EXPECTED_MUNICIPALITIES:
        raise ValueError("Cadastro de módulos fiscais incompleto.")
    return values


def fiscal_module_rows() -> tuple[tuple[str, int], ...]:
    """Return stable rows suitable for seeding SQLite."""
    return tuple(
        (code, int(hectares))
        for code, hectares in sorted(fiscal_module_sizes().items())
    )


def municipality_code_from_car(car: object) -> str:
    """Extract the seven-digit IBGE municipality code from a CAR identifier."""
    match = re.match(r"^[A-Z]{2}[- ]?(\d{7})", str(car or "").strip().upper())
    return match.group(1) if match else ""


def _positive_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        return None
    return parsed if parsed > 0 else None


def _display(value: Decimal | None, places: str = "0.0001") -> str:
    if value is None:
        return ""
    rounded = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return format(rounded.normalize(), "f")


def assess_fiscal_modules(
    car: object,
    area_ha: object,
    declared_module_count: object = None,
    municipality_code: object = None,
) -> FiscalModuleAssessment:
    """Assess only the up-to-four-fiscal-modules territorial criterion."""
    code = str(municipality_code or "").strip()
    if not re.fullmatch(r"\d{7}", code):
        code = municipality_code_from_car(car)
    area = _positive_decimal(area_ha)
    declared = _positive_decimal(declared_module_count)
    size = fiscal_module_sizes().get(code)
    count = area / size if area is not None and size is not None else declared
    limit = size * 4 if size is not None else None
    calculated_from_official_size = area is not None and size is not None
    consistency_note = ""
    if calculated_from_official_size and declared is not None and count is not None:
        if abs(count - declared) > Decimal("0.05"):
            consistency_note = (
                "A quantidade declarada na fonte do imóvel diverge do cálculo "
                "pela área e pelo módulo fiscal oficial; conferir os dados de origem."
            )

    common = {
        "municipality_code": code,
        "area_ha": _display(area),
        "module_size_ha": _display(size, "1"),
        "module_count": _display(count),
        "four_modules_ha": _display(limit, "1"),
        "declared_module_count": _display(declared),
        "calculation_source": (
            "Área do imóvel ÷ módulo fiscal oficial do município"
            if calculated_from_official_size
            else "Quantidade de módulos informada na fonte do imóvel"
            if declared is not None
            else ""
        ),
        "consistency_note": consistency_note,
        "source_rule": SOURCE_RULE,
        "source_url": SOURCE_URL,
        "source_date": SOURCE_DATE,
        "scope": (
            "CAR analisado; não consolida automaticamente outros imóveis ou "
            "áreas da mesma unidade familiar de produção agrária."
        ),
        "family_farming_qualification": (
            "não determinada automaticamente; exige CAF ativo e validação "
            "dos demais requisitos e exceções legais"
        ),
    }
    if count is None:
        return FiscalModuleAssessment(
            status="nao_verificado",
            status_label="Não foi possível verificar o limite territorial",
            rationale=(
                "Faltam a área do imóvel e/ou um código IBGE municipal válido "
                "para calcular a quantidade de módulos fiscais."
            ),
            technical_action=(
                "Conferir o CAR, o município e a área; depois validar CAF, renda, "
                "mão de obra, gestão, área total da UFPA e exceções aplicáveis."
            ),
            **common,
        )

    if count <= Decimal(4):
        status = "atende_limite"
        label = "O CAR está dentro do limite territorial de até 4 módulos fiscais"
        rationale = (
            f"A área considerada corresponde a {_display(count)} módulo(s) "
            "fiscal(is), dentro do limite geral de 4."
        )
    else:
        status = "nao_atende_limite"
        label = "O CAR excede o limite territorial geral de 4 módulos fiscais"
        rationale = (
            f"A área considerada corresponde a {_display(count)} módulo(s) "
            "fiscal(is), acima do limite geral de 4."
        )
    if consistency_note:
        rationale += f" {consistency_note}"
    return FiscalModuleAssessment(
        status=status,
        status_label=label,
        rationale=rationale,
        technical_action=(
            "Validar o CAF ativo, a área total da UFPA, renda, mão de obra, "
            "gestão e eventual enquadramento em exceção legal antes de concluir."
        ),
        **common,
    )


def assess_car_fiscal_modules(
    car: object,
    car_context: Mapping[str, object] | None = None,
    mma_records: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, str]:
    """Choose the best available CAR attributes and produce the assessment."""
    context = car_context or {}
    mma = mma_records[0] if mma_records else {}
    area = (
        context.get("area_ha") or mma.get("area_total_ha") or mma.get("area_declarada")
    )
    declared = context.get("modulos_fiscais") or mma.get("modulos_fiscais")
    code = context.get("codigo_municipio") or mma.get("codigo_municipio")
    result = assess_fiscal_modules(car, area, declared, code).as_dict()
    if context and (area or declared):
        result["property_data_source"] = "Base cadastral local do SICAR"
    elif mma and (area or declared):
        result["property_data_source"] = "Publicação MMA/MCR"
    else:
        result["property_data_source"] = "Dados do imóvel não disponíveis"
    return result
