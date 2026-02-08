# ha-urbansolar Integrations

## Description
L'intégration `ha-urbansolar` émule une **batterie virtuelle** à partir de deux index du compteur :
- **Index Base** (consommation réseau)
- **Index Injection** (énergie injectée)

Elle calcule :
- un **index réseau émulé** (Base Emulated),
- un **index batterie consommée** (Battery Out),
- un **index injection** (Injection Emulated),
- une **capacité de batterie virtuelle**.

Elle expose aussi des capteurs de **tarifs TTC** (énergie et acheminement) mis à jour depuis le PDF Urban Solar.

L'intégration `energy_price_history` permet de **reconstruire l'historique du coût** (EUR cumulés) à partir :
- d'un capteur d'énergie (kWh),
- d'un capteur coût existant (EUR),
- d'un tableau de périodes de prix (EUR/kWh, en UTC).

## Installation
1. Clonez le dépôt dans le répertoire `custom_components` de votre installation Home Assistant.
   ```bash
   git clone https://github.com/AntoineOnnillon/ha-urbansolar.git
   ```
2. Redémarrez Home Assistant.

## Configuration
Configuration via l'interface Home Assistant.

Options disponibles :
- **Tarif** : `Base (HB)` (le contrat `HP/HC` n'est pas encore pris en charge)
- **Puissance souscrite** (kVA)
- **Capteur Index Base** (device_class = `energy`)
- **Capteur Index Injection** (device_class = `energy`)
- **Rebuild historique** (recalcule les statistiques à partir des index)

## Capteurs créés
Les entités sont proposées avec des suffixes explicites :
- `sensor.battery_in_energy` : crédit total (injection)
- `sensor.battery_out_energy` : batterie consommée
- `sensor.battery_capacity` : capacité virtuelle
- `sensor.base_emulated_energy` : consommation réseau émulée
- `sensor.injection_emulated_energy` : injection émulée

## Calculs
Les calculs sont strictement basés sur les deltas d’index :
- **Battery In** = delta d’injection positif
- **Battery Out** ≤ delta base et ≤ capacité disponible
- **Capacity** = Battery In - Battery Out (jamais négative)
- **Base Emulated** = Index Base - Battery Out (jamais négatif)

## Panneau Énergie (conseillé)
Pour séparer les prix réseau et acheminement, utilisez **2 sources “grid”** :

1) **Réseau (HB)**  
   `flow_from = sensor.base_emulated_energy`

2) **Acheminement**  
   `flow_from = sensor.battery_out_energy`

Et pour l’injection :
- `flow_to = sensor.injection_emulated_energy`

Important : **ne pas configurer de batterie** dans le panneau Énergie si vous utilisez cette structure, sinon double comptage.

## Rebuild historique
Si vous activez l’option “Rebuild historique”, l’intégration :
- supprime les anciennes statistiques des capteurs dérivés,
- recalcule `sum` cumulés à partir des deltas,
- réécrit les statistiques compatibles avec le panneau Énergie.

## energy_price_history
**Objectif** : recalculer l'historique du **coût cumulé** (EUR) pour le panneau Énergie.

Configuration :
- **Capteur énergie** (device_class = `energy`)
- **Capteur coût** (EUR, capteur existant utilisé par le panneau Énergie)
- **Périodes de prix** (JSON simple `from/to/price`, UTC)
- **Rebuild historique** (recalcule et réécrit les statistiques de coût)

Important :
- Ce module **ne crée pas de capteur**.
- Il **écrit dans la base Recorder** : faites une sauvegarde avant.

## Limites actuelles
- Le contrat `HP/HC` n'est pas encore pris en charge.

## Contribuer
Les contributions sont bienvenues ! N'hésitez pas à soumettre des PR ou signaler des problèmes.

## Licence
Ce projet est sous licence MIT. Voir le fichier `LICENSE`.
