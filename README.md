# sduoj-judger
Fetch the code, compile and run it, and return the result.

## install dependency 

```
pip3 install install -r requirements.txt
```

## How to Run it

A proper setup configuration is needed before you run the judger.

You can place `config.yaml` from a template file `config.yaml.template` and the judger will read the configuration automatically. If there is no such file, the judger will read it from you system enviroment. You can set a system variable like `export AAAA=BBBB`.

Once the configuration is ready, you can run judger using following command with **root privilege**

```
python3 -m judger.server
```