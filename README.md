# Peggle-Lib PS3 - Biblioteca para o peggle de PS3

- Extração .pak PS3 [OK]
- Rebuild .pak PS3 [OK]
- Conversão levels .dat PS3 <-> PC [OK]
- Renderizador de prévia dos níveis [OK]

## Módulos

### 1. `extract.py` - Extração de .pak

Extrai todos os arquivos de dentro de um `.pak` do Peggle PS3.

```
python extract.py peggle.pak -l                     # Listar conteúdo
python extract.py peggle.pak -x ./extracted         # Extrair (PS3-correct)
python extract.py peggle.pak --raw -x ./extracted   # Extrair raw (com headers - apenas para debug)
```

- `-l` / `--list`: lista todos os arquivos internos com tamanho e offset
- `-x DIR` / `--extract DIR`: extrai os arquivos para o diretório
- `--raw`: extrai incluindo o header de 2 bytes e padding (apenas para debug) 
- O modo padrão (`extract()`) extrai apenas os dados reais do arquivo, como o jogo lê

### 2. `levelreader.py` - Leitor/Parser de .dat

Parser completo do formato binário `.dat` de níveis do Peggle (universal entre PS3 e PC).

```
python levelreader.py extracted/levels/level1.dat    # Ler e exibir um nível
python levelreader.py --all                           # Exibir todos os níveis do .pak
python levelreader.py --test                          # Round-trip test em todos
```

Suporta todos os tipos de entrada:
- **Circle** (type 5): pegs, raio
- **Rod** (type 2): haste, pontos A/B
- **Polygon** (type 3): polígonos, vértices
- **Brick** (type 6): blocos, curvos/retos
- **Teleport** (type 8): teletransportes com entrada aninhada
- **Emitter** (type 9): emissores de partículas

Também lê **PegInfo** (tipo de peg, laranja, desmoronar), **Movement** (15 tipos de movimento/animação) e **generic_flags** (rolly, bouncy, colisão, visibilidade, cores, imagens, som, lógica, etc.).

### 3. `convert_level.py` - Conversor .dat ↔ .dat / .dat ↔ JSON

Permite converter entre formatos PS3 e PC e editar níveis como JSON.

```
# .dat → JSON (edição)
python convert_level.py input.dat output.json

# JSON → .dat (especificando plataforma)
python convert_level.py input.json output.dat --pc    # PC (v0x52)
python convert_level.py input.json output.dat --ps3   # PS3 (v0x30)

# .dat ↔ .dat (conversão direta entre versões)
python convert_level.py input.dat output.dat --to-pc      # PS3 → PC (v0x52)
python convert_level.py input.dat output.dat --to-ps3     # PC → PS3 (v0x35)
python convert_level.py input.dat output.dat --to-version 0x52  # versão arbitrária

# Testar todos os níveis extraídos
python convert_level.py --test-all
```

**Diferenças PS3 vs PC:** O formato .dat é quase identico. A diferença está na **versão** do arquivo, que controla campos condicionais:
- `v < 0x0F`: flags em 24 bits
- `v >= 0x23`: fB byte em Polygon/Brick
- `v >= 0x50`: Shadow flag
- `v >= 0x52`: fB byte em Circle (PC)

O fluxo típico de edição de níveis:

1. Extraia o .pak com `extract.py`
2. Abra `.dat` do level desejado no **PeggleEdit** (editor PC), edite os níveis
3. Salve no PeggleEdit (gera .dat PC v0x52)
4. Converta de volta para PS3: `python convert_level.py level_pc.dat level_ps3.dat --to-ps3`
5. Substitua o .dat original no diretório extraído
6. Reconstrua o .pak com `repack.py`

**Alternativa (edição via JSON,Experimental):**
1. Converta .dat para JSON: `python convert_level.py level.dat level.json`
2. Edite o JSON manualmente
3. Converta de volta: `python convert_level.py level.json level_ps3.dat --ps3`

### 4. `repack.py` - Reconstrução de .pak

Reconstroi um `.pak` PS3 válido a partir dos arquivos extraídos (modificados ou não).

```
python repack.py peggle.pak ./extracted rebuilt.pak              # Rebuild
python repack.py peggle.pak ./extracted rebuilt.pak --verify     # Rebuild + verificar
python repack.py peggle.pak ./extracted rebuilt.pak --verify-only # Apenas verificar
```

- Usa o `.pak` original como referência para cabeçalhos e metadados
- Arquivos não modificados mantêm o layout original byte-a-byto
- Arquivos modificados (tamanho diferente) são escritos com `header_val=0` (sem padding)
- `--verify`: compara o .pak gerado com o original byte-a-byto
- `--verify-only`: compara sem rebuild

Se nenhum arquivo for modificado, o rebuild é **100% idêntico** ao original.

---

### 5. `levelpreview.py` - Preview PNG de níveis

Gera uma imagem PNG 800x600 reproduzindo fielmente a renderização do Peggle:
background do nível, pegs, bricks, polygons, rods, teleports, emitters, generators
e overlay da interface.

```
python levelpreview.py fish.dat preview.png
python levelpreview.py level1.dat preview.png --no-textures
python levelpreview.py --test ./caminho/com/dats
python levelpreview.py --test-one fish.dat
python levelpreview.py fish.dat preview.png --assets ./meus_assets
python levelpreview.py --test ./extracted                # Testar todos os níveis
python levelpreview.py fish.dat preview.png --debug-labels  # Mostrar IDs das entradas
```

**Opções:**
- `--no-textures` — desativa texturas; usa cores sólidas (equivalente ao preview do PeggleEdit)
- `--debug-labels` — exibe o índice numérico de cada entrada sobre o preview (útil para depuração)

## Guia de Modding Passo a Passo

### 1. Preparação

Você precisa do `.pak` original do Peggle PS3. Os principais são:
- `peggle.pak` (dados do jogo: níveis, imagens, configurações)
- Outros `.pak` podem conter DLCs,Strings e etc
### 2. Extrair o .pak

```bash
python extract.py peggle.pak -x ./extracted

Isso cria a pasta `extracted/` com toda a árvore de arquivos do jogo.

### 3. Editar Níveis (com PeggleEdit)

```bash
# Converter .dat do PS3 para PC (PeggleEdit)
python convert_level.py extracted/levels/level1.dat level_pc.dat --to-pc
(Opcional,o Peggle Edit já consegue abrir diretamente)

# Abrir level_pc.dat no PeggleEdit, editar, salvar

# Converter de volta para PS3
python convert_level.py level_pc.dat extracted/levels/level1.dat --to-ps3
```

### 4. Editar Níveis (via JSON - sem PeggleEdit)
Obs: recurso experimental,não recomendo edição via json

```bash
# Extrair para JSON
python convert_level.py extracted/levels/level1.dat level.json

# Editar level.json com qualquer editor de texto/script
# ...

# Gerar .dat PS3
python convert_level.py level.json extracted/levels/level1.dat --ps3
```

### 5. Editar Backgrounds (com PeggleEdit)

As imagens de background do Peggle PS3 têm resolução **menor** que as da versão PC. O arquivo `bg-template-peggle-editor.jpg` é um molde que mostra a área visível no PS3 dentro do canvas maior do PeggleEdit.

1. Abra o template (`bg-template-peggle-editor.jpg`) no seu editor de imagens
2. Use as marcações do template para alinhar sua arte dentro da área visível do PS3
3. Salve a imagem final no **tamanho original do PS3** (ignore o tamanho do template, ele é apenas guia)
4. Coloque a imagem no diretório extraído, substituindo a original
5. Faça o rebuild do .pak

> O template **não** deve ser incluído no .pak. Ele serve apenas para posicionamento visual dentro do PeggleEdit quando usado como background corrigindo o alinhamento do editor.

### 6. Reconstruir o .pak

```bash
# Reconstruir o .pak modificado
python repack.py peggle.pak ./extracted peggle_mod.pak --verify
```

O argumento `--verify` compara o .pak novo com o original. Se você modificou arquivos, a saída será diferente (esperado). Se não modificou nada, o rebuild será idêntico.

### 7. Testar no Jogo

Copie `peggle_mod.pak` para o seu PS3 (via FTP, USB com CFW/HEN, ou emulador RPCS3) substituindo o original. Recomenda-se fazer backup do `.pak` original antes.

---

## Formato .pak (PS3)

O formato PS3 é **sequencial**:
- **Header:** magic `0xBAC04AC0` + version `0` (8 bytes)
- **Index:** entries com flags, nome, tamanho, filetime
- **Terminator:** byte `0x80`
- **Data Section:** registros sequenciais — cada um tem:
  - 2-byte header LE (offset/padding assinado)
  - `header_val` bytes de padding (se header_val > 0)
  - `size` bytes de dados reais do arquivo

O `extract.py` lida com isso automaticamente, e o `repack.py` reconstrói o formato exato.

---

## Formato .dat

O formato `.dat` de nível é quase **idêntico** entre PS3 e PC. A única diferença é o campo `version` que altera condicionais especificas no runtime da engine dependendo de qual versão está definida (Pego,Peggle Deluxe,Peggle Nights,Peggle PS3 e etc) Ex:
- `v < 0x0F`: flags em 24 bits
- `v >= 0x23`: fB byte em Polygon/Brick
- `v >= 0x50`: Shadow flag
- `v >= 0x52`: fB byte em Circle (PC)

- **PS3:** `0x30` a `0x41` (típico)
- **PC (PeggleEdit):** `0x52`

A conversão entre versões é segura e preserva todas as entradas. As normalizações aplicadas (PegInfo.type→1, Brick fC flags, etc.) são idênticas às do PeggleEdit C# original.
